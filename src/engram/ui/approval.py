from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..anki import AnkiClient, AnkiError, AnkiUnavailableError
from ..config import Config
from ..models import CardDraft, DraftRequest, ValidationOutcome

BG = "#1e1e24"
FG = "#e8e8ee"
DIM = "#9a9aa6"
WARN = "#d9a05b"
ERR = "#d97070"
OK = "#7bc47f"


class ApprovalDialog:
    """The quality gate. Its confirm handler is the only code path in engram
    that writes to Anki — tests/test_approval_gate.py enforces that."""

    def __init__(self, root, request: DraftRequest, outcome: ValidationOutcome,
                 anki_client: AnkiClient, cfg: Config, on_done: Callable):
        self.request = request
        self.outcome = outcome
        self.anki = anki_client
        self.cfg = cfg
        self.on_done = on_done  # called with "closed" or "revise"
        self.rows = []
        self.sent = False

        top = tk.Toplevel(root)
        self.top = top
        top.title("engram — review cards")
        top.attributes("-topmost", True)
        top.configure(bg=BG, padx=14, pady=12)

        if outcome.reject_reason:
            self._build_rejection(top)
        else:
            self._build_cards(top)

        top.bind("<Escape>", lambda _e: self._close())
        top.protocol("WM_DELETE_WINDOW", self._close)
        top.lift()
        top.focus_force()

    def _build_rejection(self, top):
        tk.Label(top, text="No card suggested", bg=BG, fg=FG, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(top, text=self.outcome.reject_reason, bg=BG, fg=WARN,
                 font=("Segoe UI", 10), wraplength=460, justify="left").pack(anchor="w", pady=(6, 12))
        row = tk.Frame(top, bg=BG)
        row.pack(anchor="e")
        tk.Button(row, text="Revise memory target", command=self._revise).pack(side="left", padx=4)
        tk.Button(row, text="Close (Esc)", command=self._close).pack(side="left", padx=4)
        top.bind("<Return>", lambda _e: self._revise())

    def _revise(self):
        self.top.destroy()
        self.on_done("revise")

    def _build_cards(self, top):
        for w in self.outcome.warnings:
            tk.Label(top, text=f"⚠ {w}", bg=BG, fg=WARN, font=("Segoe UI", 9),
                     wraplength=560, justify="left").pack(anchor="w")
        for d in self.outcome.dropped:
            tk.Label(top, text=f"✗ draft dropped: {d.reason}", bg=BG, fg=DIM,
                     font=("Segoe UI", 9), wraplength=560, justify="left").pack(anchor="w")

        for card in self.outcome.accepted:
            frm = tk.Frame(top, bg=BG, pady=6)
            frm.pack(fill="x")
            include = tk.BooleanVar(value=True)
            head = tk.Frame(frm, bg=BG)
            head.pack(fill="x")
            tk.Checkbutton(head, text=f"include · {card.knowledge_type} / {card.note_format}",
                           variable=include, bg=BG, fg=FG, selectcolor="#2a2a33",
                           activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 9, "bold")).pack(side="left")
            if card.why_this_card:
                tk.Label(head, text=f"  — {card.why_this_card}", bg=BG, fg=DIM,
                         font=("Segoe UI", 9, "italic")).pack(side="left")

            front = tk.Text(frm, height=2, width=70, bg="#2a2a33", fg=FG,
                            insertbackground=FG, font=("Segoe UI", 10), relief="flat", wrap="word")
            front.insert("1.0", card.front)
            front.pack(fill="x", pady=(4, 2))
            back = tk.Text(frm, height=3, width=70, bg="#26262e", fg=FG,
                           insertbackground=FG, font=("Segoe UI", 10), relief="flat", wrap="word")
            back.insert("1.0", card.back)
            back.pack(fill="x")
            self.rows.append((include, front, back, card))

        self.status = tk.Label(top, text="", bg=BG, fg=DIM, font=("Segoe UI", 9),
                               wraplength=560, justify="left")
        self.status.pack(anchor="w", pady=(8, 4))

        row = tk.Frame(top, bg=BG)
        row.pack(anchor="e")
        self.send_btn = tk.Button(row, text=f"Add to Anki [{self.cfg.anki.deck}]  (Ctrl+Enter)",
                                  command=self._confirm)
        self.send_btn.pack(side="left", padx=4)
        tk.Button(row, text="Cancel (Esc)", command=self._close).pack(side="left", padx=4)
        # ctrl+enter approves — plain enter is just a newline in the text
        # boxes, so no accidental submits mid-edit
        top.bind("<Control-Return>", lambda _e: self._confirm())

    def _collect(self) -> list[CardDraft]:
        cards = []
        for include, front, back, card in self.rows:
            if not include.get():
                continue
            edited = card.model_copy(update={
                "front": front.get("1.0", "end-1c").strip(),
                "back": back.get("1.0", "end-1c").strip(),
            })
            if edited.front:
                cards.append(edited)
        return cards

    def _confirm(self):
        if self.sent:
            return
        cards = self._collect()
        if not cards:
            self.status.configure(text="No cards selected.", fg=WARN)
            return
        try:
            # the one and only place cards get sent to anki
            results = self.anki.add_cards(cards, self.cfg, self.request.app_class,
                                          self.request.window_title,
                                          image_b64=self.request.image_b64 or None)
        except AnkiUnavailableError as e:
            self.status.configure(text=f"{e}\nStart Anki, then press Retry — your drafts are kept.", fg=ERR)
            self.send_btn.configure(text="Retry (Ctrl+Enter)")
            return
        except AnkiError as e:
            self.status.configure(text=f"Anki error: {e}", fg=ERR)
            return

        self.sent = True
        lines = [f"✓ {status}" if status.startswith("added") else f"✗ {status}" for _c, status in results]
        self.status.configure(text="\n".join(lines), fg=OK)
        self.send_btn.configure(state="disabled")
        self.top.after(2500, self._close)

    def _close(self):
        if self.top.winfo_exists():
            self.top.destroy()
        self.on_done("closed")
