import pytest
from pydantic import ValidationError

from engram.models import CardDraft, CardDraftList


def make_card(**overrides) -> CardDraft:
    base = dict(
        knowledge_type="concept",
        note_format="basic",
        front="Why does interleaving beat blocking?",
        back="It forces discrimination between related categories.",
    )
    base.update(overrides)
    return CardDraft(**base)


def test_zero_cards_requires_reject_reason():
    with pytest.raises(ValidationError):
        CardDraftList(cards=[])


def test_zero_cards_with_reason_is_valid():
    result = CardDraftList(cards=[], reject_reason="too vague to be worth memorizing")
    assert result.reject_reason


def test_cards_with_reject_reason_is_invalid():
    with pytest.raises(ValidationError):
        CardDraftList(cards=[make_card()], reject_reason="nope")


def test_warnings_allowed_alongside_cards():
    result = CardDraftList(cards=[make_card()], warnings=["front is long"])
    assert result.warnings == ["front is long"]


def test_unknown_knowledge_type_rejected():
    with pytest.raises(ValidationError):
        make_card(knowledge_type="vibes")
