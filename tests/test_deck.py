import json

import responses

from engram.anki import AnkiClient, reconcile_deck
from engram.config import Config
from engram.models import CardDraft, CardDraftList
from engram.validators import validate_drafts

URL = "http://127.0.0.1:8765"


def test_reconcile_exact_match_reuses_existing():
    existing = ["Default", "Chess::Openings", "Biology"]
    assert reconcile_deck("chess::openings", existing, "engram") == "Chess::Openings"


def test_reconcile_no_match_keeps_suggestion_as_new():
    assert reconcile_deck("Physics::Optics", ["Default"], "engram") == "Physics::Optics"


def test_reconcile_empty_falls_back_to_default():
    assert reconcile_deck("", ["Default"], "engram") == "engram"


def test_reconcile_does_not_fuzzy_match():
    # "Chess Openings" must NOT silently fold into "Chess::Openings"
    assert reconcile_deck("Chess Openings", ["Chess::Openings"], "engram") == "Chess Openings"


def test_suggested_deck_flows_through_validation():
    draft = CardDraftList(
        cards=[CardDraft(knowledge_type="fact", note_format="basic", front="Q?", back="a")],
        suggested_deck="Chess::Openings",
    )
    outcome = validate_drafts(draft, Config().cards, 2)
    assert outcome.suggested_deck == "Chess::Openings"


@responses.activate
def test_add_cards_uses_chosen_deck():
    seen = {}

    def handler(http_request):
        payload = json.loads(http_request.body)
        action = payload["action"]
        if action == "version":
            result = 6
        elif action == "createDeck":
            seen["created"] = payload["params"]["deck"]
            result = 1
        elif action == "canAddNotes":
            result = [True]
        elif action == "addNotes":
            seen["notes"] = payload["params"]["notes"]
            result = [1]
        else:
            raise AssertionError(action)
        return 200, {}, json.dumps({"result": result, "error": None})

    responses.add_callback(responses.POST, URL, callback=handler)
    card = CardDraft(knowledge_type="fact", note_format="basic", front="Q?", back="a")
    AnkiClient(URL).add_cards([card], Config(), "browser", "w", deck="Chess::Openings")

    assert seen["created"] == "Chess::Openings"
    assert seen["notes"][0]["deckName"] == "Chess::Openings"


@responses.activate
def test_add_cards_defaults_to_config_deck():
    seen = {}

    def handler(http_request):
        payload = json.loads(http_request.body)
        action = payload["action"]
        result = {"version": 6, "createDeck": 1, "canAddNotes": [True], "addNotes": [1]}[action]
        if action == "addNotes":
            seen["deck"] = payload["params"]["notes"][0]["deckName"]
        return 200, {}, json.dumps({"result": result, "error": None})

    responses.add_callback(responses.POST, URL, callback=handler)
    card = CardDraft(knowledge_type="fact", note_format="basic", front="Q?", back="a")
    AnkiClient(URL).add_cards([card], Config(), "browser", "w")  # no deck override
    assert seen["deck"] == "engram"


@responses.activate
def test_deck_names_safe_returns_empty_when_anki_down():
    import requests

    responses.add(responses.POST, URL, body=requests.exceptions.ConnectionError("refused"))
    assert AnkiClient(URL).deck_names_safe() == []
