from pathlib import Path

import pytest

from engram.config import ConfigError, ensure_config_file, load_config


def test_first_run_creates_default_config(tmp_path: Path):
    path = tmp_path / ".engram" / "config.toml"
    cfg = load_config(path)
    assert path.exists()
    assert cfg.llm.provider == "manual"
    assert cfg.llm.max_cards == 2
    assert cfg.anki.deck == "engram"
    assert cfg.anki.basic_front_field == "Front"
    assert cfg.cards.cloze_max_deletions == 2


def test_ensure_config_is_idempotent(tmp_path: Path):
    path = tmp_path / "config.toml"
    ensure_config_file(path)
    path.write_text('[llm]\nprovider = "fake"\n', encoding="utf-8")
    ensure_config_file(path)  # must not overwrite
    assert load_config(path).llm.provider == "fake"


def test_unknown_provider_rejected(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[llm]\nprovider = "chatgpt"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="chatgpt"):
        load_config(path)


def test_bad_toml_is_a_config_error(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[llm\nbroken", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_max_cards_must_be_positive(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[llm]\nmax_cards = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
