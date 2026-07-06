import json

import pytest
import requests
import responses

from engram.anki import (
    AnkiClient,
    AnkiConnectError,
    AnkiUnavailableError,
    build_tags,
    sanitize_tag,
)
from engram.config import Config
from engram.models import CardDraft

URL = "http://127.0.0.1:8765"
CFG = Config()


def card(**overrides) -> CardDraft:
    base = dict(
        knowledge_type="fact",
        note_format="basic",
        front="What is X?",
        back="Y",
    )
    base.update(overrides)
    return CardDraft(**base)


def add_rpc(action_results: dict):
    """Register one mocked AnkiConnect endpoint that dispatches on action."""

    def handler(request):
        payload = json.loads(request.body)
        action = payload["action"]
        assert payload["version"] <= 6
        result = action_results[action]
        result = result(payload) if callable(result) else result
        return 200, {}, json.dumps({"result": result, "error": None})

    responses.add_callback(responses.POST, URL, callback=handler)


@responses.activate
def test_connection_refused_raises_unavailable():
    responses.add(responses.POST, URL, body=requests.exceptions.ConnectionError("refused"))
    with pytest.raises(AnkiUnavailableError, match="2055492159"):
        AnkiClient(URL).connect()


@responses.activate
def test_version_negotiation_caps_at_supported():
    add_rpc({"version": 7})
    client = AnkiClient(URL)
    assert client.connect() == 7
    assert client._protocol == 6  # we never send a higher version than we support


@responses.activate
def test_version_negotiation_uses_lower_reported():
    add_rpc({"version": 5})
    client = AnkiClient(URL)
    client.connect()
    assert client._protocol == 5


@responses.activate
def test_ankiconnect_error_surfaces():
    responses.add(
        responses.POST, URL,
        json={"result": None, "error": "collection is not available"},
    )
    with pytest.raises(AnkiConnectError, match="collection"):
        AnkiClient(URL).deck_names()


@responses.activate
def test_check_setup_reports_missing_model_and_field():
    add_rpc({
        "version": 6,
        "modelNames": ["Basic"],  # no Cloze model
        "modelFieldNames": ["Front", "Wrong"],
    })
    client = AnkiClient(URL)
    client.connect()
    problems = client.check_setup(CFG)
    assert any("Cloze" in p for p in problems)
    assert any('"Back"' in p for p in problems)


@responses.activate
def test_add_cards_payload_and_duplicate_reporting(caplog):
    import logging

    seen = {}

    def can_add(payload):
        seen["canAddNotes"] = payload["params"]["notes"]
        return [True, False]

    def add_notes(payload):
        seen["addNotes"] = payload["params"]["notes"]
        return [1501]

    add_rpc({
        "version": 6,
        "createDeck": 1,
        "canAddNotes": can_add,
        "addNotes": add_notes,
    })

    cards = [card(), card(front="Duplicate front?", back="dup")]
    client = AnkiClient(URL)
    with caplog.at_level(logging.INFO, logger="engram.anki"):
        results = client.add_cards(cards, CFG, app_class="browser", window_title="w")

    # the push totals are logged, so "why did only N land?" is answerable later
    assert "anki push: deck=engram sent=2 added=1 skipped=1" in caplog.text

    # basic card mapped to configured model/fields
    note = seen["addNotes"][0]
    assert note["modelName"] == "Basic"
    assert note["fields"] == {"Front": "What is X?", "Back": "Y"}
    assert note["deckName"] == "engram"
    assert "engram" in note["tags"]
    assert note["options"] == {"allowDuplicate": False}

    statuses = dict((c.front, s) for c, s in results)
    assert statuses["What is X?"].startswith("added")
    assert statuses["Duplicate front?"] == "skipped by Anki duplicate/validation check"


@responses.activate
def test_cloze_cards_use_cloze_model_and_fields():
    captured = {}

    def can_add(payload):
        captured["notes"] = payload["params"]["notes"]
        return [True]

    add_rpc({"version": 6, "createDeck": 1, "canAddNotes": can_add, "addNotes": [7]})
    cloze = card(note_format="cloze", front="X is {{c1::Y}}.", back="extra")
    AnkiClient(URL).add_cards([cloze], CFG, "pdf", "w")
    note = captured["notes"][0]
    assert note["modelName"] == "Cloze"
    assert note["fields"] == {"Text": "X is {{c1::Y}}.", "Back Extra": "extra"}


@responses.activate
def test_extra_rider_lands_dim_below_back():
    captured = {}

    def can_add(payload):
        captured["notes"] = payload["params"]["notes"]
        return [True]

    add_rpc({"version": 6, "createDeck": 1, "canAddNotes": can_add, "addNotes": [8]})
    c = card(knowledge_type="archetype", front="How to solve X? (2)",
             back="1. reduce 2. recurse", extra="Note: only normalise at the end")
    AnkiClient(URL).add_cards([c], CFG, "pdf", "w")
    back = captured["notes"][0]["fields"]["Back"]
    assert back.startswith("1. reduce 2. recurse")
    assert "only normalise at the end" in back
    assert "color:#8a8a8a" in back  # dim rider, visually not the recall target


def test_sanitize_tag_strips_spaces_and_junk():
    assert sanitize_tag("my secret doc.pdf - Adobe") == "my_secret_doc.pdf_-_Adobe"
    assert " " not in sanitize_tag("a b c")


def test_build_tags_conservative_by_default():
    tags = build_tags(card(), app_class="browser", window_title="Private chat with boss", cfg=CFG)
    assert "engram" in tags
    assert "engram::fact" in tags
    assert "engram::source_browser" in tags
    assert not any("Private" in t or "boss" in t for t in tags)  # titles off by default
