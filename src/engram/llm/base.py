from __future__ import annotations

import re
from typing import Callable, Protocol

from pydantic import ValidationError

from ..models import CardDraftList, DraftRequest


class LLMDraftError(Exception):
    def __init__(self, message, raw_text=""):
        super().__init__(message)
        self.raw_text = raw_text


class MissingAPIKeyError(Exception):
    pass


class LLMClient(Protocol):
    def draft_cards(self, req: DraftRequest) -> CardDraftList: ...


FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

CORRECTIVE_MESSAGE = (
    "Your previous output was not a valid JSON object matching the required "
    "schema. Respond again with ONLY the JSON object — no prose, no code fences."
)


def strip_fences(text: str) -> str:
    return FENCE_RE.sub("", text.strip()).strip()


def parse_draft_json(text: str) -> CardDraftList:
    cleaned = strip_fences(text)
    try:
        return CardDraftList.model_validate_json(cleaned)
    except ValidationError as e:
        raise LLMDraftError(f"model output failed schema validation: {e}", raw_text=text) from e
    except ValueError as e:
        raise LLMDraftError(f"model output was not valid JSON: {e}", raw_text=text) from e


def draft_with_retry(send: Callable[[str | None], str]) -> CardDraftList:
    # one corrective retry, then give up with the raw text attached
    first = send(None)
    try:
        return parse_draft_json(first)
    except LLMDraftError:
        return parse_draft_json(send(CORRECTIVE_MESSAGE))
