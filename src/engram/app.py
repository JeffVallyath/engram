"""Tray app + event loop, plus CLI hooks so each layer can be tested alone
(--draft, --anki-check, --capture-test, --ui-test).

tkinter owns the main thread; the hotkey hook thread and LLM worker threads
only ever talk to it through a queue drained by root.after().
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import __version__
from .anki import AnkiClient, AnkiUnavailableError
from .config import CONFIG_PATH, Config, ConfigError, load_config
from .llm import LLMDraftError, MissingAPIKeyError, make_client
from .models import (
    CaptureEvent,
    CaptureResult,
    DraftFailed,
    DraftReady,
    DraftRequest,
    QuitEvent,
    ValidationOutcome,
)
from .router import template_drafts
from .validators import validate_drafts

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\engram_single_instance"


def only_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def build_request(capture: CaptureResult, kt: str, note: str, cfg: Config) -> DraftRequest:
    return DraftRequest(
        knowledge_type=kt,
        selected_text=capture.text,
        user_note=note,
        window_title=capture.window_title,
        app_class=capture.app_class,
        max_cards=cfg.llm.max_cards,
    )


def draft_outcome(client, req: DraftRequest, cfg: Config) -> ValidationOutcome:
    if client is None:
        # manual mode: skeleton templates would fail the prompt validators by
        # design, so skip the drop pass — the human is the drafting step here
        return ValidationOutcome(
            accepted=template_drafts(req),
            warnings=["manual mode — fill in the template before adding"],
        )
    return validate_drafts(client.draft_cards(req), cfg.cards, req.max_cards)


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        self.anki = AnkiClient(cfg.anki.url)
        self.client = make_client(cfg)  # None in manual mode
        self.busy = False  # a picker or review dialog is open
        self.tray = None

    # background threads -> queue

    def on_hotkey(self):
        from .capture import capture_selection

        if self.busy:
            return
        self.q.put(CaptureEvent(capture_selection(self.cfg.capture)))

    def draft_worker(self, req: DraftRequest):
        try:
            self.q.put(DraftReady(req, draft_outcome(self.client, req, self.cfg)))
        except LLMDraftError as e:
            self.q.put(DraftFailed(req, str(e), e.raw_text))
        except MissingAPIKeyError as e:
            self.q.put(DraftFailed(req, str(e)))
        except Exception as e:
            log.exception("draft worker failed")
            self.q.put(DraftFailed(req, f"Drafting failed: {e}"))

    # main-thread side

    def poll(self):
        try:
            while True:
                ev = self.q.get_nowait()
                if isinstance(ev, QuitEvent):
                    self.shutdown()
                    return
                if isinstance(ev, CaptureEvent):
                    self.handle_capture(ev.capture)
                elif isinstance(ev, DraftReady):
                    self.open_review(ev.request, ev.outcome)
                elif isinstance(ev, DraftFailed):
                    self.show_draft_failure(ev)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def handle_capture(self, capture, initial_note=""):
        from .ui.picker import TypePicker

        if capture is None:
            self.toast("No text selected")
            return
        if self.busy:
            return
        self.busy = True

        def on_submit(kt, note):
            req = build_request(capture, kt, note, self.cfg)
            log.info("capture accepted: type=%s app=%s chars=%d", kt, capture.app_class, len(capture.text))
            if self.client is None:
                self.open_review(req, draft_outcome(None, req, self.cfg))
            else:
                self.toast("Drafting…")
                threading.Thread(target=self.draft_worker, args=(req,), daemon=True).start()

        def on_cancel():
            self.busy = False

        TypePicker(self.root, capture, on_submit, on_cancel, initial_note=initial_note)

    def open_review(self, req: DraftRequest, outcome: ValidationOutcome):
        from .ui.approval import ApprovalDialog

        self.busy = True

        def on_done(action):
            self.busy = False
            if action == "revise":
                capture = CaptureResult(
                    text=req.selected_text,
                    window_title=req.window_title,
                    app_class=req.app_class,
                    prior_clipboard_was_text=True,
                )
                self.handle_capture(capture, initial_note=req.user_note)

        ApprovalDialog(self.root, req, outcome, self.anki, self.cfg, on_done)

    def show_draft_failure(self, ev: DraftFailed):
        self.busy = False
        detail = f"\n\nRaw model output:\n{ev.raw_text[:800]}" if ev.raw_text else ""
        messagebox.showerror("engram — drafting failed", ev.message + detail)

    def toast(self, text, ms=1400):
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        tk.Label(top, text=text, bg="#1e1e24", fg="#e8e8ee", padx=14, pady=8,
                 font=("Segoe UI", 10)).pack()
        top.geometry(f"+{self.root.winfo_pointerx() + 10}+{self.root.winfo_pointery() + 10}")
        top.after(ms, top.destroy)

    def make_tray(self):
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((8, 8, 56, 56), fill=(79, 140, 201, 255))
        d.ellipse((22, 22, 42, 42), fill=(30, 30, 36, 255))

        def open_config(_icon, _item):
            import os
            os.startfile(CONFIG_PATH.parent)

        def quit_app(_icon, _item):
            self.q.put(QuitEvent())

        menu = pystray.Menu(
            pystray.MenuItem("Open config folder", open_config),
            pystray.MenuItem("Quit engram", quit_app),
        )
        self.tray = pystray.Icon("engram", img,
                                 f"engram ({self.cfg.llm.provider}) — {self.cfg.hotkey.combo}", menu)
        self.tray.run_detached()

    def shutdown(self):
        from . import hotkey

        try:
            hotkey.unregister_all()
        except Exception:
            pass
        if self.tray is not None:
            self.tray.stop()
        self.root.quit()

    def run(self) -> int:
        from . import hotkey

        if not only_instance():
            messagebox.showerror("engram", "engram is already running (check the system tray).")
            return 1

        hotkey.register(self.cfg.hotkey.combo, self.on_hotkey)
        self.make_tray()
        log.info("engram started: hotkey=%s provider=%s deck=%s",
                 self.cfg.hotkey.combo, self.cfg.llm.provider, self.cfg.anki.deck)
        self.root.after(100, self.poll)
        self.root.mainloop()
        return 0


# cli hooks

def cli_draft(cfg: Config, args) -> int:
    req = DraftRequest(
        knowledge_type=args.type,
        selected_text=args.draft,
        user_note=args.note or "",
        window_title="(cli)",
        app_class="cli",
        max_cards=cfg.llm.max_cards,
    )
    try:
        outcome = draft_outcome(make_client(cfg), req, cfg)
    except (LLMDraftError, MissingAPIKeyError) as e:
        print(f"draft failed: {e}", file=sys.stderr)
        raw = getattr(e, "raw_text", "")
        if raw:
            print(f"raw model output:\n{raw}", file=sys.stderr)
        return 1

    if outcome.reject_reason:
        print(f"NO CARD: {outcome.reject_reason}")
        return 0
    for card in outcome.accepted:
        print(f"[{card.knowledge_type}/{card.note_format}] {card.why_this_card}")
        print(f"  FRONT: {card.front}")
        print(f"  BACK:  {card.back}")
    for d in outcome.dropped:
        print(f"dropped: {d.reason}")
    for w in outcome.warnings:
        print(f"warning: {w}")
    return 0


def cli_anki_check(cfg: Config) -> int:
    client = AnkiClient(cfg.anki.url)
    try:
        reported = client.connect()
    except AnkiUnavailableError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"AnkiConnect reachable - reports protocol version {reported}")
    print(f"decks: {', '.join(client.deck_names())}")
    problems = client.check_setup(cfg)
    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        return 1
    print("configured note models and fields all exist - good to go")
    return 0


def cli_capture_test(cfg: Config) -> int:
    import keyboard as kb

    from . import hotkey
    from .capture import capture_selection

    def on_hot():
        res = capture_selection(cfg.capture)
        if res is None:
            print("(no text selected)")
        else:
            print(f"[{res.app_class}] {res.window_title!r}")
            print(f"  {res.text[:200]!r}")

    hotkey.register(cfg.hotkey.combo, on_hot)
    print(f"capture test: select text anywhere and press {cfg.hotkey.combo} (Ctrl+C here to stop)")
    kb.wait()
    return 0


def cli_ui_test(cfg: Config) -> int:
    from .llm.fake import FakeClient
    from .ui.picker import TypePicker

    class DryRunAnki(AnkiClient):
        def add_cards(self, cards, cfg_, app_class, window_title):
            return [(c, f"added (dry-run) {c.front[:40]!r}") for c in cards]

    root = tk.Tk()
    root.withdraw()
    capture = CaptureResult(
        text="Interleaving improves discrimination between related categories, "
             "while spacing gives rest between encounters of the same item.",
        window_title="ui-test", app_class="test", prior_clipboard_was_text=True,
    )

    def on_submit(kt, note):
        from .ui.approval import ApprovalDialog

        req = build_request(capture, kt, note, cfg)
        outcome = validate_drafts(FakeClient().draft_cards(req), cfg.cards, req.max_cards)
        ApprovalDialog(root, req, outcome, DryRunAnki(), cfg, lambda _a: root.quit())

    TypePicker(root, capture, on_submit, root.quit)
    root.mainloop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="engram",
                                     description="Global-hotkey Anki capture with a knowledge-type router.")
    parser.add_argument("--version", action="version", version=f"engram {__version__}")
    parser.add_argument("--draft", metavar="TEXT", help="draft cards for TEXT on the console (no UI)")
    parser.add_argument("--type", default="concept",
                        choices=["fact", "concept", "procedure", "formula", "cloze", "custom"])
    parser.add_argument("--note", help="memory-target note for --draft")
    parser.add_argument("--provider", help="override llm.provider for this run (e.g. fake, manual)")
    parser.add_argument("--anki-check", action="store_true", help="check AnkiConnect, deck, models and fields")
    parser.add_argument("--capture-test", action="store_true", help="print captures to the console")
    parser.add_argument("--ui-test", action="store_true", help="drive the UI with fake data (no Anki writes)")
    args = parser.parse_args(argv)

    from .logging_setup import setup_logging

    setup_logging()
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    if args.provider:
        from dataclasses import replace

        cfg = replace(cfg, llm=replace(cfg.llm, provider=args.provider.lower()))

    if args.draft:
        return cli_draft(cfg, args)
    if args.anki_check:
        return cli_anki_check(cfg)
    if args.capture_test:
        return cli_capture_test(cfg)
    if args.ui_test:
        return cli_ui_test(cfg)

    return App(cfg).run()


if __name__ == "__main__":
    raise SystemExit(main())
