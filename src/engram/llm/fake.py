from __future__ import annotations

from ..models import CardDraft, CardDraftList, DraftRequest
from ..router import default_note_format


class FakeClient:
    """Offline drafts so the whole loop runs without a key. Short selections
    get rejected, which also demos the zero-card path."""

    def draft_cards(self, req: DraftRequest) -> CardDraftList:
        txt = req.selected_text.strip()
        if len(txt) < 15:
            return CardDraftList(
                cards=[],
                reject_reason="Selection is too short to yield a durable, self-contained card.",
            )

        topic = " ".join(txt.split()[:6])
        fmt = default_note_format(req.knowledge_type)
        if fmt == "cloze":
            card = CardDraft(
                knowledge_type=req.knowledge_type,
                note_format="cloze",
                front="The captured passage is about {{c1::" + topic + "}}.",
                back="",
                tags=["fake"],
                why_this_card="fake offline draft (cloze)",
            )
        else:
            card = CardDraft(
                knowledge_type=req.knowledge_type,
                note_format="basic",
                front=f"What is the key idea of: {topic}...?",
                back=txt[:200],
                tags=["fake"],
                why_this_card="fake offline draft (basic)",
            )
        return CardDraftList(cards=[card])
