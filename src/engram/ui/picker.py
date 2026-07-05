from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..models import CaptureResult
from .theme import ACCENT, BG, DIM, FG

HEADER = "What do you want to be able to recall or do later?"
NOTE_HINT = (
    "e.g. distinguish X from Y · remember when to use this · recall the assumption · test the boundary case"
)
TYPE_KEYS = {
    "7": ("auto", "7 Auto"),
    "1": ("fact", "1 Fact"),
    "2": ("concept", "2 Concept"),
    "3": ("procedure", "3 Procedure"),
    "4": ("formula", "4 Formula"),
    "5": ("cloze", "5 Cloze"),
    "6": ("custom", "6 Custom"),
}
PICKABLE = {kt for kt, _ in TYPE_KEYS.values()}

CARDS_LIMIT = 5


class TypePicker:
    def __init__(self, root, capture: CaptureResult, on_submit: Callable, on_cancel: Callable,
                 initial_note="", initial_cards=2, max_limit=CARDS_LIMIT):
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.picked = "auto"
        self.labels = {}
        self.hint_showing = False
        self.limit = max_limit
        self.cards_n = max(1, min(initial_cards, max_limit))

        top = tk.Toplevel(root)
        self.top = top
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=BG, padx=14, pady=12, highlightthickness=1, highlightbackground=ACCENT)

        tk.Label(top, text=HEADER, bg=BG, fg=FG, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        snippet = " ".join(capture.text.split())[:90]
        tk.Label(top, text=f"“{snippet}…”", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 8))

        self.note = tk.Entry(top, width=64, bg="#2a2a33", fg=FG, insertbackground=FG,
                             font=("Segoe UI", 10), relief="flat")
        self.note.pack(fill="x", ipady=5)
        if initial_note:
            self.note.insert(0, initial_note)
        else:
            self._show_hint()
        self.note.bind("<FocusIn>", self._hide_hint)

        row = tk.Frame(top, bg=BG)
        row.pack(anchor="w", pady=(8, 2))
        for key, (kt, label) in TYPE_KEYS.items():
            lbl = tk.Label(row, text=label, bg=BG, fg=DIM, font=("Segoe UI", 9), padx=6, pady=2, cursor="hand2")
            lbl.pack(side="left", padx=2)
            lbl.bind("<Button-1>", lambda _e, t=kt: self._pick(t))
            self.labels[kt] = lbl
        self._pick(self.picked)

        cards_row = tk.Frame(top, bg=BG)
        cards_row.pack(anchor="w", pady=(4, 2))
        tk.Label(cards_row, text="max cards:", bg=BG, fg=DIM, font=("Segoe UI", 9)).pack(side="left")
        minus = tk.Label(cards_row, text=" − ", bg=BG, fg=FG, font=("Segoe UI", 10, "bold"), cursor="hand2")
        minus.pack(side="left")
        minus.bind("<Button-1>", lambda _e: self._bump_cards(-1))
        self.cards_lbl = tk.Label(cards_row, text=str(self.cards_n), bg=ACCENT, fg=FG,
                                  font=("Segoe UI", 9, "bold"), padx=6)
        self.cards_lbl.pack(side="left")
        plus = tk.Label(cards_row, text=" + ", bg=BG, fg=FG, font=("Segoe UI", 10, "bold"), cursor="hand2")
        plus.pack(side="left")
        plus.bind("<Button-1>", lambda _e: self._bump_cards(1))

        tk.Label(top, text="1-7 pick type · ↑↓ max cards · 0 skip (no card) · Enter draft · Esc cancel",
                 bg=BG, fg=DIM, font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))

        for key, (kt, _label) in TYPE_KEYS.items():
            top.bind(f"<KeyPress-{key}>", lambda e, t=kt: self._on_digit(e, t))
        top.bind("<KeyPress-0>", self._on_zero)
        top.bind("<Up>", lambda _e: self._bump_cards(1))
        top.bind("<Down>", lambda _e: self._bump_cards(-1))
        top.bind("<Return>", lambda _e: self._submit())
        top.bind("<Escape>", lambda _e: self._cancel())

        self._place_near_pointer(root)
        top.lift()
        top.focus_force()
        self.note.focus_set()

    def _show_hint(self):
        self.hint_showing = True
        self.note.insert(0, NOTE_HINT)
        self.note.configure(fg=DIM)

    def _hide_hint(self, _e=None):
        if self.hint_showing:
            self.note.delete(0, "end")
            self.note.configure(fg=FG)
            self.hint_showing = False

    def _note_text(self):
        return "" if self.hint_showing else self.note.get().strip()

    def _on_digit(self, event, kt):
        # digits typed into the note field are text, not type selection
        if event.widget is self.note and not self.hint_showing:
            return None
        self._hide_hint()
        self.note.focus_set()
        self._pick(kt)
        return "break"

    def _on_zero(self, event):
        if event.widget is self.note and not self.hint_showing:
            return None
        self._cancel()
        return "break"

    def _pick(self, kt):
        assert kt in PICKABLE
        self.picked = kt
        for t, lbl in self.labels.items():
            lbl.configure(fg=FG if t == kt else DIM, bg=ACCENT if t == kt else BG)

    def _bump_cards(self, delta):
        self.cards_n = max(1, min(self.cards_n + delta, self.limit))
        self.cards_lbl.configure(text=str(self.cards_n))

    def _place_near_pointer(self, root):
        self.top.update_idletasks()
        x, y = root.winfo_pointerx() + 12, root.winfo_pointery() + 12
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        x = min(x, root.winfo_screenwidth() - w - 10)
        y = min(y, root.winfo_screenheight() - h - 10)
        self.top.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _submit(self):
        note = self._note_text()
        self.top.destroy()
        self.on_submit(self.picked, note, self.cards_n)

    def _cancel(self):
        self.top.destroy()
        self.on_cancel()
