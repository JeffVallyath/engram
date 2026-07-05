from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

KnowledgeType = Literal["fact", "concept", "procedure", "formula", "cloze", "custom"]
NoteFormat = Literal["basic", "cloze"]

KNOWLEDGE_TYPES = ("fact", "concept", "procedure", "formula", "cloze", "custom")


class CardDraft(BaseModel):
    knowledge_type: KnowledgeType
    note_format: NoteFormat
    front: str
    back: str = ""
    tags: list[str] = Field(default_factory=list)
    why_this_card: str = ""  # shown in the review dialog, never sent to anki


class CardDraftList(BaseModel):
    cards: list[CardDraft] = Field(default_factory=list)
    reject_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        if not self.cards and not self.reject_reason:
            raise ValueError("zero cards requires a reject_reason")
        if self.cards and self.reject_reason:
            raise ValueError("reject_reason must be null when cards are present")
        return self


@dataclass(frozen=True)
class DraftRequest:
    knowledge_type: str
    selected_text: str
    user_note: str
    window_title: str
    app_class: str
    max_cards: int
    image_b64: str = ""  # set for snap captures, empty for text captures


@dataclass
class CaptureResult:
    text: str
    window_title: str
    app_class: str
    prior_clipboard_was_text: bool


@dataclass
class DroppedCard:
    card: CardDraft
    reason: str


@dataclass
class ValidationOutcome:
    accepted: list[CardDraft]
    dropped: list[DroppedCard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reject_reason: Optional[str] = None


# stuff the background threads push onto the queue for the tk main loop

@dataclass
class CaptureEvent:
    capture: Optional[CaptureResult]  # None = nothing selected


@dataclass
class SnapEvent:
    window_title: str
    app_class: str


@dataclass
class DraftReady:
    request: DraftRequest
    outcome: ValidationOutcome


@dataclass
class DraftFailed:
    request: DraftRequest
    message: str
    raw_text: str = ""


@dataclass
class QuitEvent:
    pass
