from __future__ import annotations

import datetime
import re

import requests

from .config import Config
from .models import CardDraft

SUPPORTED_PROTOCOL = 6
ADDON_CODE = "2055492159"

TAG_JUNK_RE = re.compile(r"[^A-Za-z0-9_\-:.]+")


class AnkiError(Exception):
    pass


class AnkiUnavailableError(AnkiError):
    pass


class AnkiConnectError(AnkiError):
    pass


def sanitize_tag(tag: str) -> str:
    return TAG_JUNK_RE.sub("_", tag.strip())[:60].strip("_")


def reconcile_deck(suggested: str, existing: list[str], default: str) -> str:
    """Map the model's suggested deck onto reality: reuse an existing deck on an
    exact (case-insensitive) match, otherwise keep the suggestion as a new deck.
    No fuzzy matching — that's how unrelated cards get grouped together."""
    s = (suggested or "").strip()
    if not s:
        return default
    by_lower = {d.lower(): d for d in existing}
    return by_lower.get(s.lower(), s)


def build_tags(card: CardDraft, app_class: str, window_title: str, cfg: Config) -> list[str]:
    today = datetime.date.today().isoformat()
    tags = [
        "engram",
        f"engram::{today}",
        f"engram::{card.knowledge_type}",
        f"engram::source_{sanitize_tag(app_class) or 'unknown'}",
    ]
    tags += [sanitize_tag(t) for t in cfg.anki.tags]
    tags += [sanitize_tag(t) for t in card.tags]
    if cfg.capture.tag_window_title and window_title.strip():
        # off by default, titles leak document names
        tags.append("engram::title_" + sanitize_tag(window_title)[:40])
    return [t for t in dict.fromkeys(tags) if t]


class AnkiClient:
    def __init__(self, url="http://127.0.0.1:8765", timeout=3.0):
        self.url = url
        self.timeout = timeout
        self._protocol = None

    def _invoke(self, action, **params):
        payload = {"action": action, "version": self._protocol or SUPPORTED_PROTOCOL}
        if params:
            payload["params"] = params
        try:
            resp = requests.post(self.url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise AnkiUnavailableError(
                f"Could not reach AnkiConnect at {self.url}. Is Anki running with "
                f"the AnkiConnect add-on (code {ADDON_CODE}) installed?"
            ) from e
        if isinstance(data, dict) and data.get("error"):
            raise AnkiConnectError(str(data["error"]))
        return data["result"] if isinstance(data, dict) else data

    def connect(self):
        # negotiate instead of assume: send whichever protocol is lower,
        # ours or the one the add-on reports
        reported = int(self._invoke("version"))
        self._protocol = min(reported, SUPPORTED_PROTOCOL)
        return reported

    def deck_names(self):
        return self._invoke("deckNames")

    def deck_names_safe(self) -> list[str]:
        # for the review dialog: never raise, just return [] if anki is down
        try:
            if self._protocol is None:
                self.connect()
            return self.deck_names()
        except AnkiError:
            return []

    def ensure_deck(self, name):
        self._invoke("createDeck", deck=name)

    def model_names(self):
        return self._invoke("modelNames")

    def model_field_names(self, model):
        return self._invoke("modelFieldNames", modelName=model)

    def check_setup(self, cfg: Config) -> list[str]:
        problems = []
        models = set(self.model_names())
        checks = [
            (cfg.anki.basic_model, [cfg.anki.basic_front_field, cfg.anki.basic_back_field]),
            (cfg.anki.cloze_model, [cfg.anki.cloze_text_field, cfg.anki.cloze_extra_field]),
        ]
        for model, wanted in checks:
            if model not in models:
                problems.append(f'note model "{model}" does not exist in Anki')
                continue
            have = set(self.model_field_names(model))
            for f in wanted:
                if f not in have:
                    problems.append(f'model "{model}" has no field "{f}" (has: {", ".join(sorted(have))})')
        return problems

    def _note(self, card: CardDraft, cfg: Config, tags: list[str], img_tag="", deck=None) -> dict:
        a = cfg.anki
        back = card.back + img_tag
        if card.note_format == "cloze":
            model, fields = a.cloze_model, {a.cloze_text_field: card.front, a.cloze_extra_field: back}
        else:
            model, fields = a.basic_model, {a.basic_front_field: card.front, a.basic_back_field: back}
        return {
            "deckName": deck or a.deck,
            "modelName": model,
            "fields": fields,
            "tags": tags,
            "options": {"allowDuplicate": False},
        }

    def add_cards(self, cards, cfg: Config, app_class: str, window_title: str,
                  image_b64=None, image_mode="first", deck=None):
        """The single write path to Anki — only ever called from the review
        dialog's confirm handler (tests enforce this)."""
        deck = deck or cfg.anki.deck
        if self._protocol is None:
            self.connect()
        self.ensure_deck(deck)

        img_tag = ""
        if image_b64 and image_mode != "none":
            fname = f"engram_{int(datetime.datetime.now().timestamp() * 1000)}.png"
            self._invoke("storeMediaFile", filename=fname, data=image_b64)
            img_tag = f'<br><img src="{fname}">'

        # "first": screenshot on card 0 only, so one card's answer image can't
        # leak the answers to its siblings in the same review session
        notes = [
            self._note(c, cfg, build_tags(c, app_class, window_title, cfg),
                       img_tag if (image_mode == "all" or i == 0) else "", deck=deck)
            for i, c in enumerate(cards)
        ]
        addable = self._invoke("canAddNotes", notes=notes)

        results = []
        to_add, add_idx = [], []
        for i, (card, ok) in enumerate(zip(cards, addable)):
            if ok:
                to_add.append(notes[i])
                add_idx.append(i)
            else:
                # canAddNotes conflates dupes and invalid note params
                results.append((card, "skipped by Anki duplicate/validation check"))

        if to_add:
            ids = self._invoke("addNotes", notes=to_add)
            for i, note_id in zip(add_idx, ids):
                status = f"added (note {note_id})" if note_id else "Anki refused to add this note"
                results.append((cards[i], status))

        order = {id(c): i for i, c in enumerate(cards)}
        results.sort(key=lambda pair: order[id(pair[0])])
        return results
