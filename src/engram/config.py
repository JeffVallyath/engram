from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS = ("anthropic", "openai", "manual", "fake")

CONFIG_DIR = Path.home() / ".engram"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# written to ~/.engram/config.toml on first run, so keys never live in the repo
DEFAULT_TOML = """\
# engram config — see config.example.toml in the repo for the full docs.

[llm]
provider = "manual"          # anthropic | openai | manual | fake
model = "claude-haiku-4-5"
api_key_env = "ANTHROPIC_API_KEY"
max_cards = 2                # hard ceiling, the popup note can never raise it

[hotkey]
# ctrl+shift+a collides with chrome's tab search, so alt it is
combo = "ctrl+alt+a"
snap_combo = "ctrl+alt+s"    # region screenshot -> vision draft

[anki]
url = "http://127.0.0.1:8765"
deck = "engram"
tags = []
basic_model = "Basic"
basic_front_field = "Front"
basic_back_field = "Back"
cloze_model = "Cloze"
cloze_text_field = "Text"
cloze_extra_field = "Back Extra"

[capture]
clipboard_timeout_ms = 500
tag_window_title = false

[snap]
# "first" = screenshot on the back of the first card only (default — avoids one
# card's answer image leaking the answers to its sibling cards),
# "all" = on every card, "none" = never
attach_image = "first"

[cards]
front_max_chars = 200
back_max_chars = 500
cloze_max_deletions = 2
"""


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "manual"
    model: str = "claude-haiku-4-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_cards: int = 2


@dataclass(frozen=True)
class HotkeyConfig:
    combo: str = "ctrl+alt+a"
    snap_combo: str = "ctrl+alt+s"


@dataclass(frozen=True)
class AnkiConfig:
    url: str = "http://127.0.0.1:8765"
    deck: str = "engram"
    tags: tuple[str, ...] = ()
    basic_model: str = "Basic"
    basic_front_field: str = "Front"
    basic_back_field: str = "Back"
    cloze_model: str = "Cloze"
    cloze_text_field: str = "Text"
    cloze_extra_field: str = "Back Extra"


@dataclass(frozen=True)
class CaptureConfig:
    clipboard_timeout_ms: int = 500
    tag_window_title: bool = False


@dataclass(frozen=True)
class SnapConfig:
    attach_image: str = "first"  # first | all | none


@dataclass(frozen=True)
class CardsConfig:
    front_max_chars: int = 200
    back_max_chars: int = 500
    cloze_max_deletions: int = 2


@dataclass(frozen=True)
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    anki: AnkiConfig = field(default_factory=AnkiConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    cards: CardsConfig = field(default_factory=CardsConfig)
    snap: SnapConfig = field(default_factory=SnapConfig)


def ensure_config_file(path: Path = CONFIG_PATH) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML, encoding="utf-8")
    return path


def load_config(path: Path = CONFIG_PATH) -> Config:
    ensure_config_file(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"couldn't parse {path}: {e}") from e

    llm_raw = raw.get("llm", {})
    anki_raw = raw.get("anki", {})
    cap_raw = raw.get("capture", {})
    cards_raw = raw.get("cards", {})

    llm = LLMConfig(
        provider=str(llm_raw.get("provider", "manual")).lower(),
        model=str(llm_raw.get("model", "claude-haiku-4-5")),
        api_key_env=str(llm_raw.get("api_key_env", "ANTHROPIC_API_KEY")),
        max_cards=int(llm_raw.get("max_cards", 2)),
    )
    if llm.provider not in PROVIDERS:
        raise ConfigError(
            f"unknown llm.provider {llm.provider!r} in {path} — expected one of {', '.join(PROVIDERS)}"
        )
    if llm.max_cards < 1:
        raise ConfigError(f"llm.max_cards must be >= 1 (got {llm.max_cards})")

    return Config(
        llm=llm,
        hotkey=HotkeyConfig(
            combo=str(raw.get("hotkey", {}).get("combo", "ctrl+alt+a")),
            snap_combo=str(raw.get("hotkey", {}).get("snap_combo", "ctrl+alt+s")),
        ),
        anki=AnkiConfig(
            url=str(anki_raw.get("url", "http://127.0.0.1:8765")),
            deck=str(anki_raw.get("deck", "engram")),
            tags=tuple(str(t) for t in anki_raw.get("tags", [])),
            basic_model=str(anki_raw.get("basic_model", "Basic")),
            basic_front_field=str(anki_raw.get("basic_front_field", "Front")),
            basic_back_field=str(anki_raw.get("basic_back_field", "Back")),
            cloze_model=str(anki_raw.get("cloze_model", "Cloze")),
            cloze_text_field=str(anki_raw.get("cloze_text_field", "Text")),
            cloze_extra_field=str(anki_raw.get("cloze_extra_field", "Back Extra")),
        ),
        capture=CaptureConfig(
            clipboard_timeout_ms=int(cap_raw.get("clipboard_timeout_ms", 500)),
            tag_window_title=bool(cap_raw.get("tag_window_title", False)),
        ),
        cards=CardsConfig(
            front_max_chars=int(cards_raw.get("front_max_chars", 200)),
            back_max_chars=int(cards_raw.get("back_max_chars", 500)),
            cloze_max_deletions=int(cards_raw.get("cloze_max_deletions", 2)),
        ),
        snap=SnapConfig(attach_image=_attach_mode(raw.get("snap", {}).get("attach_image", "first"), path)),
    )


def _attach_mode(val, path):
    if isinstance(val, bool):  # old-style true/false still accepted
        return "all" if val else "none"
    mode = str(val).lower()
    if mode not in ("first", "all", "none"):
        raise ConfigError(f'snap.attach_image in {path} must be "first", "all" or "none" (got {val!r})')
    return mode
