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
    IngestFailed,
    IngestPickEvent,
    IngestReady,
    QuitEvent,
    SnapEvent,
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


def build_request(capture: CaptureResult, kt: str, note: str, cfg: Config, n=None) -> DraftRequest:
    return DraftRequest(
        knowledge_type=kt,
        selected_text=capture.text,
        user_note=note,
        window_title=capture.window_title,
        app_class=capture.app_class,
        max_cards=n or cfg.llm.max_cards,
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
        self.busy = False  # a picker or review dialog is open
        self.tray = None
        # a missing key or sdk must not kill the app — fall back to manual mode
        self.client = None
        self.llm_error = None
        try:
            self.client = make_client(cfg)  # None in manual mode
        except (MissingAPIKeyError, LLMDraftError) as e:
            self.llm_error = str(e)

    # background threads -> queue

    def on_hotkey(self):
        from .capture import capture_selection

        if self.busy:
            return
        self.q.put(CaptureEvent(capture_selection(self.cfg.capture)))

    def on_snap_hotkey(self):
        from .capture import active_app_class, active_window_title

        if self.busy:
            return
        # grab window info here, before the overlay takes over the screen
        self.q.put(SnapEvent(active_window_title(), active_app_class()))

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
                elif isinstance(ev, SnapEvent):
                    self.handle_snap(ev)
                elif isinstance(ev, IngestPickEvent):
                    self.pick_ingest_file()
                elif isinstance(ev, IngestReady):
                    self.ingest_picker(ev.text, ev.filename)
                elif isinstance(ev, IngestFailed):
                    messagebox.showerror("engram — ingest failed", ev.message)
                elif isinstance(ev, DraftReady):
                    self.open_review(ev.request, ev.outcome)
                elif isinstance(ev, DraftFailed):
                    self.show_draft_failure(ev)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def handle_capture(self, capture, initial_note="", initial_cards=None):
        from .ui.picker import TypePicker

        if capture is None:
            self.toast("No text selected")
            return
        if self.busy:
            return
        self.busy = True

        def on_submit(kt, note, n):
            req = build_request(capture, kt, note, self.cfg, n)
            log.info("capture accepted: type=%s app=%s chars=%d cards<=%d",
                     kt, capture.app_class, len(capture.text), n)
            if self.client is None:
                self.open_review(req, draft_outcome(None, req, self.cfg))
            else:
                self.toast("Drafting…")
                threading.Thread(target=self.draft_worker, args=(req,), daemon=True).start()

        def on_cancel():
            self.busy = False

        TypePicker(self.root, capture, on_submit, on_cancel, initial_note=initial_note,
                   initial_cards=initial_cards or self.cfg.llm.max_cards)

    def handle_snap(self, ev: SnapEvent):
        from .snap import grab_region, to_b64_png

        if self.busy:
            return
        self.busy = True
        img = grab_region(self.root)
        if img is None:
            self.busy = False
            return
        self.busy = False
        self.snap_picker(ev, to_b64_png(img))

    def snap_picker(self, ev: SnapEvent, img_b64: str, initial_note="", initial_cards=None):
        from .ui.picker import TypePicker

        self.busy = True
        capture = CaptureResult(
            text="[screenshot]", window_title=ev.window_title,
            app_class=ev.app_class, prior_clipboard_was_text=True,
        )

        def on_submit(kt, note, n):
            req = DraftRequest(
                knowledge_type=kt,
                selected_text="",
                user_note=note,
                window_title=ev.window_title,
                app_class=ev.app_class,
                max_cards=n,
                image_b64=img_b64,
            )
            log.info("snap accepted: type=%s app=%s cards<=%d", kt, ev.app_class, n)
            if self.client is None:
                self.open_review(req, draft_outcome(None, req, self.cfg))
            else:
                self.toast("Drafting from screenshot…")
                threading.Thread(target=self.draft_worker, args=(req,), daemon=True).start()

        def on_cancel():
            self.busy = False

        TypePicker(self.root, capture, on_submit, on_cancel, initial_note=initial_note,
                   initial_cards=initial_cards or self.cfg.llm.max_cards)

    def pick_ingest_file(self):
        from tkinter import filedialog

        from .ingest import FILETYPES, IngestError, extract_text

        if self.busy:
            return
        if self.client is None:
            messagebox.showerror(
                "engram", "Ingest needs an LLM provider — set llm.provider to "
                "anthropic or openai in ~/.engram/config.toml.")
            return
        path = filedialog.askopenfilename(title="engram — ingest a file", filetypes=FILETYPES)
        if not path:
            return
        self.toast("Reading file…")

        def worker():
            from pathlib import Path

            try:
                text = extract_text(path)
            except IngestError as e:
                self.q.put(IngestFailed(str(e)))
                return
            self.q.put(IngestReady(text, Path(path).name))

        threading.Thread(target=worker, daemon=True).start()

    def ingest_picker(self, text: str, filename: str, initial_note="", initial_cards=None):
        from .ingest import BUDGET_LIMIT, DEFAULT_BUDGET
        from .ui.picker import TypePicker

        if self.busy:
            return
        self.busy = True
        capture = CaptureResult(
            text=text, window_title=filename, app_class="file",
            prior_clipboard_was_text=True,
        )

        def on_submit(kt, note, n):
            req = DraftRequest(
                knowledge_type=kt,
                selected_text=text,
                user_note=note,
                window_title=filename,
                app_class="file",
                max_cards=n,
                ingest=True,
            )
            log.info("ingest accepted: file=%s type=%s cards<=%d chars=%d",
                     filename, kt, n, len(text))
            self.toast(f"Drafting up to {n} cards from {filename}…")
            threading.Thread(target=self.draft_worker, args=(req,), daemon=True).start()

        def on_cancel():
            self.busy = False

        TypePicker(self.root, capture, on_submit, on_cancel, initial_note=initial_note,
                   initial_cards=initial_cards or DEFAULT_BUDGET, max_limit=BUDGET_LIMIT)

    def open_review(self, req: DraftRequest, outcome: ValidationOutcome):
        from .ui.approval import ApprovalDialog

        self.busy = True

        def on_done(action, note=None):
            self.busy = False
            if action == "revise":
                note = note if note is not None else req.user_note
                if req.image_b64:
                    self.snap_picker(SnapEvent(req.window_title, req.app_class),
                                     req.image_b64, initial_note=note, initial_cards=req.max_cards)
                    return
                if req.ingest:
                    self.ingest_picker(req.selected_text, req.window_title,
                                       initial_note=note, initial_cards=req.max_cards)
                    return
                capture = CaptureResult(
                    text=req.selected_text,
                    window_title=req.window_title,
                    app_class=req.app_class,
                    prior_clipboard_was_text=True,
                )
                self.handle_capture(capture, initial_note=note, initial_cards=req.max_cards)

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

        def ingest_file(_icon, _item):
            self.q.put(IngestPickEvent())

        menu = pystray.Menu(
            pystray.MenuItem("Ingest a file…", ingest_file),
            pystray.MenuItem("Open config folder", open_config),
            pystray.MenuItem("Quit engram", quit_app),
        )
        self.tray = pystray.Icon(
            "engram", img,
            f"engram ({self.cfg.llm.provider}) — {self.cfg.hotkey.combo} text, "
            f"{self.cfg.hotkey.snap_combo} snap", menu)
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
        hotkey.register(self.cfg.hotkey.snap_combo, self.on_snap_hotkey)
        self.make_tray()
        if self.llm_error:
            log.warning("llm drafting disabled: %s", self.llm_error)
            messagebox.showwarning(
                "engram", f"LLM drafting disabled — {self.llm_error}\n\n"
                "Running in manual mode until this is fixed (captures still work, "
                "you write the cards yourself).")
        log.info("engram started: hotkey=%s snap=%s provider=%s deck=%s",
                 self.cfg.hotkey.combo, self.cfg.hotkey.snap_combo,
                 self.cfg.llm.provider, self.cfg.anki.deck)
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
        max_cards=args.cards or cfg.llm.max_cards,
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
    if outcome.omitted:
        print(f"omitted targets (card-worthy, not drafted): {'; '.join(outcome.omitted)}")
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


def cli_ingest(cfg: Config, args) -> int:
    from dataclasses import replace as dc_replace

    from .ingest import BUDGET_LIMIT, DEFAULT_BUDGET, IngestError, extract_text

    client = make_client(cfg)
    if client is None:
        print("ingest needs an llm provider — set llm.provider to anthropic/openai "
              "(or fake to try the flow) in ~/.engram/config.toml", file=sys.stderr)
        return 2
    try:
        text = extract_text(args.ingest)
    except IngestError as e:
        print(f"ingest error: {e}", file=sys.stderr)
        return 1

    from pathlib import Path

    budget = min(args.cards or DEFAULT_BUDGET, BUDGET_LIMIT)
    req = DraftRequest(
        knowledge_type=args.type,
        selected_text=text,
        user_note=args.note or "",
        window_title=Path(args.ingest).name,
        app_class="file",
        max_cards=budget,
        ingest=True,
    )
    print(f"drafting up to {budget} cards from {req.window_title} ({len(text):,} chars)...")

    def draft(r):
        try:
            return draft_outcome(client, r, cfg)
        except (LLMDraftError, MissingAPIKeyError) as e:
            print(f"draft failed: {e}", file=sys.stderr)
            raw = getattr(e, "raw_text", "")
            if raw:
                print(f"raw model output:\n{raw}", file=sys.stderr)
            return None

    outcome = draft(req)
    if outcome is None:
        return 1

    if args.print:
        if outcome.reject_reason:
            print(f"NO CARD: {outcome.reject_reason}")
        for card in outcome.accepted:
            print(f"[{card.knowledge_type}/{card.note_format}] {card.why_this_card}")
            print(f"  FRONT: {card.front}")
            print(f"  BACK:  {card.back}")
        for d in outcome.dropped:
            print(f"dropped: {d.reason}")
        if outcome.omitted:
            print(f"omitted targets: {'; '.join(outcome.omitted)}")
        return 0

    # normal path: the same review gate as every other capture
    from .ui.approval import ApprovalDialog

    root = tk.Tk()
    root.withdraw()
    anki = AnkiClient(cfg.anki.url)

    def open_dialog(r, oc):
        def on_done(action, note=None):
            if action == "revise":
                r2 = dc_replace(r, user_note=note if note is not None else r.user_note)
                oc2 = draft(r2)
                if oc2 is not None:
                    open_dialog(r2, oc2)
                    return
            root.quit()

        ApprovalDialog(root, r, oc, anki, cfg, on_done)

    open_dialog(req, outcome)
    root.mainloop()
    return 0


def cli_capture_test(cfg: Config) -> int:
    import time

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
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


def cli_ui_test(cfg: Config) -> int:
    from .llm.fake import FakeClient
    from .ui.picker import TypePicker

    class DryRunAnki(AnkiClient):
        def add_cards(self, cards, cfg_, app_class, window_title, image_b64=None, image_mode="first"):
            return [(c, f"added (dry-run) {c.front[:40]!r}") for c in cards]

    root = tk.Tk()
    root.withdraw()
    capture = CaptureResult(
        text="Interleaving improves discrimination between related categories, "
             "while spacing gives rest between encounters of the same item.",
        window_title="ui-test", app_class="test", prior_clipboard_was_text=True,
    )

    def on_submit(kt, note, n):
        from .ui.approval import ApprovalDialog

        req = build_request(capture, kt, note, cfg, n)
        outcome = validate_drafts(FakeClient().draft_cards(req), cfg.cards, req.max_cards)
        ApprovalDialog(root, req, outcome, DryRunAnki(), cfg, lambda *_: root.quit())

    TypePicker(root, capture, on_submit, root.quit)
    root.mainloop()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="engram",
                                     description="Global-hotkey Anki capture with a knowledge-type router.")
    parser.add_argument("--version", action="version", version=f"engram {__version__}")
    parser.add_argument("--draft", metavar="TEXT", help="draft cards for TEXT on the console (no UI)")
    parser.add_argument("--type", default="auto",
                        choices=["auto", "fact", "concept", "procedure", "formula", "cloze", "custom"])
    parser.add_argument("--note", help="memory-target note for --draft")
    parser.add_argument("--cards", type=int, help="max cards for --draft (default from config)")
    parser.add_argument("--provider", help="override llm.provider for this run (e.g. fake, manual)")
    parser.add_argument("--ingest", metavar="FILE", help="draft a coverage card set from a pdf/txt/md file")
    parser.add_argument("--print", action="store_true", help="with --ingest/--draft: console output, no review dialog")
    parser.add_argument("--anki-check", action="store_true", help="check AnkiConnect, deck, models and fields")
    parser.add_argument("--capture-test", action="store_true", help="print captures to the console")
    parser.add_argument("--ui-test", action="store_true", help="drive the UI with fake data (no Anki writes)")
    args = parser.parse_args(argv)

    from .logging_setup import setup_logging

    setup_logging()
    try:
        # per-monitor dpi awareness so snap coordinates map 1:1 to pixels
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
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
    if args.ingest:
        return cli_ingest(cfg, args)
    if args.anki_check:
        return cli_anki_check(cfg)
    if args.capture_test:
        return cli_capture_test(cfg)
    if args.ui_test:
        return cli_ui_test(cfg)

    return App(cfg).run()


if __name__ == "__main__":
    raise SystemExit(main())
