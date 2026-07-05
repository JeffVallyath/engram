import json

import responses

from engram.anki import AnkiClient
from engram.config import Config
from engram.models import CardDraft, DraftRequest
from engram.router import build_user_prompt

URL = "http://127.0.0.1:8765"


def snap_request(**overrides):
    base = dict(
        knowledge_type="concept",
        selected_text="",
        user_note="how do the encoder blocks connect",
        window_title="paper.pdf - Chrome",
        app_class="browser",
        max_cards=2,
        image_b64="aGVsbG8=",
    )
    base.update(overrides)
    return DraftRequest(**base)


def test_snap_prompt_describes_image_source():
    prompt = build_user_prompt(snap_request())
    assert "SCREENSHOT" in prompt
    assert "BEGIN CAPTURED TEXT" not in prompt
    assert "how do the encoder blocks connect" in prompt


def test_text_prompt_unchanged_without_image():
    prompt = build_user_prompt(snap_request(image_b64="", selected_text="some text"))
    assert "BEGIN CAPTURED TEXT" in prompt
    assert "SCREENSHOT" not in prompt


@responses.activate
def test_add_cards_stores_image_and_embeds_it():
    seen = {}

    def handler(http_request):
        payload = json.loads(http_request.body)
        action = payload["action"]
        if action == "version":
            result = 6
        elif action == "createDeck":
            result = 1
        elif action == "storeMediaFile":
            seen["media"] = payload["params"]
            result = payload["params"]["filename"]
        elif action == "canAddNotes":
            result = [True]
        elif action == "addNotes":
            seen["notes"] = payload["params"]["notes"]
            result = [99]
        else:
            raise AssertionError(f"unexpected action {action}")
        return 200, {}, json.dumps({"result": result, "error": None})

    responses.add_callback(responses.POST, URL, callback=handler)

    card = CardDraft(knowledge_type="concept", note_format="basic",
                     front="How do the encoder blocks connect?", back="Residually.")
    AnkiClient(URL).add_cards([card], Config(), "browser", "w", image_b64="aGVsbG8=")

    assert seen["media"]["data"] == "aGVsbG8="
    fname = seen["media"]["filename"]
    assert fname.startswith("engram_") and fname.endswith(".png")
    assert f'<img src="{fname}">' in seen["notes"][0]["fields"]["Back"]


@responses.activate
def test_add_cards_without_image_stores_nothing():
    actions = []

    def handler(http_request):
        payload = json.loads(http_request.body)
        actions.append(payload["action"])
        result = {"version": 6, "createDeck": 1, "canAddNotes": [True], "addNotes": [1]}[payload["action"]]
        return 200, {}, json.dumps({"result": result, "error": None})

    responses.add_callback(responses.POST, URL, callback=handler)
    card = CardDraft(knowledge_type="fact", note_format="basic", front="Q?", back="A")
    AnkiClient(URL).add_cards([card], Config(), "cli", "w")
    assert "storeMediaFile" not in actions
