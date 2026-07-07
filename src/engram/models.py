from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

KnowledgeType = Literal["fact", "concept", "procedure", "formula", "cloze", "custom",
                        "archetype", "intuition", "derivation"]
NoteFormat = Literal["basic", "cloze"]


class CardDraft(BaseModel):
    knowledge_type: KnowledgeType
    note_format: NoteFormat
    front: str
    back: str = ""
    # subtlety / mnemonic / why-it-works note shown alongside the answer in
    # anki (dim, below the back) — never part of the graded recall target
    extra: str = ""
    tags: list[str] = Field(default_factory=list)
    why_this_card: str = ""  # shown in the review dialog, never sent to anki


class CardDraftList(BaseModel):
    cards: list[CardDraft] = Field(default_factory=list)
    reject_reason: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    # card-worthy targets the model saw but didn't draft (kept under the
    # ceiling). empty = nothing else worth carding; non-empty = more exists
    omitted_targets: list[str] = Field(default_factory=list)
    # topic deck path the model proposes for this set (e.g. "Chess::Openings")
    suggested_deck: str = ""

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
    ingest: bool = False  # true when the text is a whole document, not a selection
    # non-empty = a "draft omitted" redraft: card ONLY these targets, at most
    # one card each — never a fresh coverage pass over the source
    redraft_targets: tuple[str, ...] = ()


@dataclass
class CaptureResult:
    text: str
    window_title: str
    app_class: str


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
    omitted: list[str] = field(default_factory=list)
    suggested_deck: str = ""


# stuff the background threads push onto the queue for the tk main loop

@dataclass
class CaptureEvent:
    capture: Optional[CaptureResult]  # None = nothing selected


@dataclass
class SnapEvent:
    window_title: str
    app_class: str


@dataclass
class IngestPickEvent:
    pass


@dataclass
class IngestLinkEvent:
    pass


@dataclass
class IngestPasteEvent:
    pass


@dataclass
class IngestReady:
    text: str
    filename: str
    app_class: str = "file"


@dataclass
class IngestFailed:
    message: str


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
