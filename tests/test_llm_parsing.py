import json

import pytest

from engram.llm.base import (
    CORRECTIVE_MESSAGE,
    LLMDraftError,
    draft_with_retry,
    parse_draft_json,
    strip_fences,
)
from engram.llm.fake import FakeClient
from engram.models import DraftRequest

VALID_PAYLOAD = json.dumps(
    {
        "cards": [
            {
                "knowledge_type": "fact",
                "note_format": "basic",
                "front": "What year did X happen?",
                "back": "1969",
                "tags": [],
                "why_this_card": "recalls a discrete fact",
            }
        ],
        "reject_reason": None,
        "warnings": [],
    }
)


def request(text="Interleaving improves discrimination between related categories.") -> DraftRequest:
    return DraftRequest(
        knowledge_type="concept",
        selected_text=text,
        user_note="",
        window_title="t",
        app_class="test",
        max_cards=2,
    )


def test_parse_valid_json():
    result = parse_draft_json(VALID_PAYLOAD)
    assert result.cards[0].front == "What year did X happen?"


def test_strip_fences():
    fenced = f"```json\n{VALID_PAYLOAD}\n```"
    assert parse_draft_json(fenced).cards


def test_strip_fences_plain_text_untouched():
    assert strip_fences("hello") == "hello"


def test_invalid_json_raises_with_raw_text():
    with pytest.raises(LLMDraftError) as err:
        parse_draft_json("sorry, I can't do JSON today")
    assert "sorry" in err.value.raw_text


def test_retry_recovers_after_one_bad_response():
    calls = []

    def send(corrective):
        calls.append(corrective)
        return "garbage" if corrective is None else VALID_PAYLOAD

    result = draft_with_retry(send)
    assert result.cards
    assert calls == [None, CORRECTIVE_MESSAGE]


def test_retry_gives_up_after_second_failure():
    def send(_corrective):
        return "still garbage"

    with pytest.raises(LLMDraftError):
        draft_with_retry(send)


def test_fake_client_returns_valid_drafts():
    drafts = FakeClient().draft_cards(request())
    assert drafts.cards
    assert drafts.reject_reason is None


def test_fake_client_zero_card_path():
    drafts = FakeClient().draft_cards(request(text="tiny"))
    assert not drafts.cards
    assert drafts.reject_reason
