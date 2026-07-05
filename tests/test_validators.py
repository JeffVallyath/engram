from engram.config import CardsConfig
from engram.models import CardDraft, CardDraftList
from engram.validators import validate_drafts

CFG = CardsConfig()


def card(**overrides) -> CardDraft:
    base = dict(
        knowledge_type="concept",
        note_format="basic",
        front="When does Bayes' rule NOT apply?",
        back="When events are not well-defined or priors are unknowable.",
    )
    base.update(overrides)
    return CardDraft(**base)


def run(*cards: CardDraft, max_cards: int = 2):
    return validate_drafts(CardDraftList(cards=list(cards)), CFG, max_cards)


def test_good_card_accepted():
    outcome = run(card())
    assert len(outcome.accepted) == 1
    assert not outcome.dropped


def test_reject_reason_passes_through():
    outcome = validate_drafts(
        CardDraftList(cards=[], reject_reason="not worth memorizing"), CFG, 2
    )
    assert outcome.reject_reason == "not worth memorizing"
    assert not outcome.accepted


def test_over_max_cards_dropped_not_silently():
    outcome = run(card(), card(front="Why is spacing effective?"), card(front="Name the third thing?"), max_cards=2)
    assert len(outcome.accepted) == 2
    assert len(outcome.dropped) == 1
    assert "max_cards" in outcome.dropped[0].reason


def test_statement_front_dropped():
    outcome = run(card(front="The mitochondria is the powerhouse of the cell."))
    assert not outcome.accepted
    assert "not a question" in outcome.dropped[0].reason


def test_prompt_verb_front_accepted():
    outcome = run(card(front="Explain why spacing beats massing."))
    assert len(outcome.accepted) == 1


def test_empty_back_dropped():
    outcome = run(card(back="  "))
    assert "empty back" in outcome.dropped[0].reason


def test_dangling_referent_dropped():
    outcome = run(card(front="What is this?"))
    assert "dangling referent" in outcome.dropped[0].reason


def test_cloze_without_deletion_dropped():
    outcome = run(card(note_format="cloze", front="A sentence with no deletion at all.", back=""))
    assert "cloze card without" in outcome.dropped[0].reason


def test_valid_cloze_accepted():
    outcome = run(card(note_format="cloze", front="Spacing works via {{c1::consolidation}}.", back=""))
    assert len(outcome.accepted) == 1


def test_too_many_cloze_deletions_warns_but_keeps():
    front = "A {{c1::one}} B {{c2::two}} C {{c3::three}}."
    outcome = run(card(note_format="cloze", front=front, back=""))
    assert len(outcome.accepted) == 1
    assert any("cloze deletions" in w for w in outcome.warnings)


def test_long_back_warns_but_keeps():
    outcome = run(card(back="x" * 600))
    assert len(outcome.accepted) == 1
    assert any("back exceeds" in w for w in outcome.warnings)
