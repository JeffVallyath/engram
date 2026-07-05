from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..anki import AnkiClient, AnkiError, AnkiUnavailableError, reconcile_deck
from ..config import Config
from ..models import CardDraft, DraftRequest, ValidationOutcome
from .theme import BG, DIM, ERR, FG, OK, WARN


class ApprovalDialog:
    """The quality gate. Its confirm handler is the only code path in engram
    that writes to Anki — tests/test_approval_gate.py enforces that."""

    def __init__(self, root, request: DraftRequest, outcome: ValidationOutcome,
                 anki_client: AnkiClient, cfg: Config, on_done: Callable):
        self.request = request
        self.outcome = outcome
        self.anki = anki_client
        self.cfg = cfg
        self.on_done = on_done  # ("closed"|"revise"|"draft_more", note, carry_cards)
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
        self.on_done("revise", None)

    def _draft_more(self):
        # keep the cards already on screen, draft the omitted ones, and merge
        # them into one review so it all sends to anki in a single push. carry
        # the deck the user chose so they don't have to re-pick it
        kept = self._collect()
        note = "Draft cards for these omitted targets: " + "; ".join(self.outcome.omitted)
        self.top.destroy()
        self.on_done("draft_more", note, (kept, self._chosen_deck()))

    def _build_cards(self, top):
        for w in self.outcome.warnings:
            tk.Label(top, text=f"⚠ {w}", bg=BG, fg=WARN, font=("Segoe UI", 9),
                     wraplength=560, justify="left").pack(anchor="w")
        for d in self.outcome.dropped:
            tk.Label(top, text=f"✗ draft dropped: {d.reason}", bg=BG, fg=DIM,
                     font=("Segoe UI", 9), wraplength=560, justify="left").pack(anchor="w")
        if self.outcome.omitted:
            n = len(self.outcome.omitted)
            tk.Label(top,
                     text=f"⚠ {n} more card-worthy target{'s' if n > 1 else ''} detected, "
                          f"not drafted: {'; '.join(self.outcome.omitted)}",
                     bg=BG, fg=WARN, font=("Segoe UI", 9), wraplength=560,
                     justify="left").pack(anchor="w")

        # ingest can produce a dozen cards — scroll instead of a 4000px dialog
        if len(self.outcome.accepted) > 3:
            wrap = tk.Frame(top, bg=BG)
            wrap.pack(fill="both", expand=True)
            canvas = tk.Canvas(wrap, bg=BG, height=520, width=620, highlightthickness=0)
            sb = tk.Scrollbar(wrap, command=canvas.yview)
            host = tk.Frame(canvas, bg=BG)
            host.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=host, anchor="nw")
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            top.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units"))
        else:
            host = top

        for card in self.outcome.accepted:
            frm = tk.Frame(host, bg=BG, pady=6)
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

        self._build_deck_row(top)

        self.status = tk.Label(top, text="", bg=BG, fg=DIM, font=("Segoe UI", 9),
                               wraplength=560, justify="left")
        self.status.pack(anchor="w", pady=(8, 4))

        row = tk.Frame(top, bg=BG)
        row.pack(anchor="e")
        if self.outcome.omitted:
            tk.Button(row, text="Draft omitted (keep these)",
                      command=self._draft_more).pack(side="left", padx=4)
        self.send_btn = tk.Button(row, text=f"Add to Anki [{self.cfg.anki.deck}]  (Ctrl+Enter)",
                                  command=self._confirm)
        self.send_btn.pack(side="left", padx=4)
        tk.Button(row, text="Cancel (Esc)", command=self._close).pack(side="left", padx=4)
        # ctrl+enter approves — plain enter is just a newline in the text
        # boxes, so no accidental submits mid-edit
        top.bind("<Control-Return>", lambda _e: self._confirm())

    def _build_deck_row(self, top):
        # ask anki what decks exist, default to the model's topic suggestion
        # reconciled against them; the user can retarget or type a new path
        existing = self.anki.deck_names_safe()
        self._existing = set(existing)
        default = reconcile_deck(self.outcome.suggested_deck, existing, self.cfg.anki.deck)

        row = tk.Frame(top, bg=BG)
        row.pack(anchor="w", pady=(8, 0), fill="x")
        tk.Label(row, text="Deck:", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).pack(side="left")

        values = sorted(existing)
        if default not in self._existing:
            values = [default] + values
        self.deck_var = tk.StringVar(value=default)
        combo = ttk.Combobox(row, textvariable=self.deck_var, values=values, width=44)
        combo.pack(side="left", padx=6)

        self.deck_hint = tk.Label(row, text="", bg=BG, font=("Segoe UI", 8))
        self.deck_hint.pack(side="left")

        def refresh_hint(*_):
            v = self.deck_var.get().strip()
            if not v:
                self.deck_hint.configure(text="", fg=DIM)
            elif v in self._existing:
                self.deck_hint.configure(text="existing deck", fg=OK)
            else:
                self.deck_hint.configure(text="new deck — will be created", fg=WARN)

        self.deck_var.trace_add("write", refresh_hint)
        refresh_hint()

    def _chosen_deck(self) -> str:
        var = getattr(self, "deck_var", None)
        return (var.get().strip() if var else "") or self.cfg.anki.deck

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
        img = self.request.image_b64 if self.cfg.snap.attach_image != "none" else ""
        try:
            # the one and only place cards get sent to anki
            results = self.anki.add_cards(cards, self.cfg, self.request.app_class,
                                          self.request.window_title,
                                          image_b64=img or None,
                                          image_mode=self.cfg.snap.attach_image,
                                          deck=self._chosen_deck())
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
        self.on_done("closed", None, None)
