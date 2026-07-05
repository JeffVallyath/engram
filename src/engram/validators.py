from __future__ import annotations

import re

from .config import CardsConfig
from .models import CardDraft, CardDraftList, DroppedCard, ValidationOutcome

CLOZE_RE = re.compile(r"\{\{c(\d+)::(.+?)\}\}", re.DOTALL)
VAGUE_RE = re.compile(r"^\s*what\s+(is|are|does|do)\s+(this|that|these|those)\s*\??\s*$", re.IGNORECASE)
DEMONSTRATIVE_RE = re.compile(r"^\s*(this|that|these|those)\b", re.IGNORECASE)

PROMPT_VERBS = {
    "explain", "define", "name", "list", "describe", "state", "give", "compare",
    "distinguish", "derive", "prove", "identify", "summarize", "contrast",
    "recall", "complete", "fill", "translate", "convert", "solve",
    "when", "why", "what", "how", "who", "where", "which", "under", "in",
}


def _is_prompt(front: str) -> bool:
    s = front.strip()
    if s.endswith("?") or s.endswith(":"):
        return True
    first = re.split(r"[\s,:]+", s.lower(), maxsplit=1)[0]
    return first in PROMPT_VERBS


def _dealbreaker(card: CardDraft):
    front = card.front.strip()
    if not front:
        return "empty front"
    if card.note_format == "cloze":
        if not CLOZE_RE.search(front):
            return "cloze card without a valid {{cN::...}} deletion"
        return None
    if not card.back.strip():
        return "empty back"
    if front.lower() == card.back.strip().lower():
        return "front and back are identical"
    if VAGUE_RE.match(front):
        return 'dangling referent ("What is this?" with no referent on the card)'
    if not _is_prompt(front):
        return "front is not a question or explicit prompt"
    return None


def _nitpicks(card: CardDraft, cfg: CardsConfig) -> list[str]:
    warns = []
    front = card.front.strip()
    label = f'"{front[:40]}..."' if len(front) > 40 else f'"{front}"'
    if len(front) > cfg.front_max_chars:
        warns.append(f"{label}: front exceeds {cfg.front_max_chars} chars")
    if len(card.back) > cfg.back_max_chars:
        warns.append(f"{label}: back exceeds {cfg.back_max_chars} chars — likely a pasted paragraph")
    if card.note_format == "cloze":
        deletions = {m.group(1) for m in CLOZE_RE.finditer(front)}
        if len(deletions) > cfg.cloze_max_deletions:
            warns.append(f"{label}: {len(deletions)} cloze deletions (max recommended {cfg.cloze_max_deletions})")
    elif DEMONSTRATIVE_RE.match(front):
        warns.append(f"{label}: starts with a demonstrative — check the referent is on the card")
    return warns


def validate_drafts(draft: CardDraftList, cards_cfg: CardsConfig, max_cards: int) -> ValidationOutcome:
    """Dealbreakers drop a card (with a visible reason), nitpicks become
    warnings. Nothing gets dropped silently, and max_cards is enforced here
    no matter what the model returned."""
    warns = list(draft.warnings)
    if draft.reject_reason:
        return ValidationOutcome(accepted=[], warnings=warns, reject_reason=draft.reject_reason)

    kept, dropped = [], []
    for card in draft.cards:
        if len(kept) >= max_cards:
            dropped.append(DroppedCard(card, f"over the max_cards ceiling ({max_cards})"))
            continue
        reason = _dealbreaker(card)
        if reason:
            dropped.append(DroppedCard(card, reason))
            continue
        warns.extend(_nitpicks(card, cards_cfg))
        kept.append(card)

    return ValidationOutcome(accepted=kept, dropped=dropped, warnings=warns,
                             omitted=list(draft.omitted_targets))
