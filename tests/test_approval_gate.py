# guardrail: nothing reaches anki except through the review dialog's confirm
# handler (app.py is allowed only for its --ui-test dry-run stub)

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "engram"

ALLOWED_CALL_FILES = {"approval.py"}
ALLOWED_DEF_FILES = {"anki.py", "app.py"}  # app.py: DryRunAnki override for --ui-test

CALL_RE = re.compile(r"\.add_cards\(")
DEF_RE = re.compile(r"def add_cards\(")
RAW_ACTION_RE = re.compile(r"[\"']addNotes[\"']")


def test_add_cards_called_only_from_approval_dialog():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if CALL_RE.search(text) and path.name not in ALLOWED_CALL_FILES | ALLOWED_DEF_FILES:
            offenders.append(path.name)
    assert not offenders, f".add_cards( called outside the approval dialog: {offenders}"


def test_add_cards_defined_only_in_expected_files():
    offenders = []
    for path in SRC.rglob("*.py"):
        if DEF_RE.search(path.read_text(encoding="utf-8")) and path.name not in ALLOWED_DEF_FILES:
            offenders.append(path.name)
    assert not offenders, f"unexpected add_cards definition in: {offenders}"


def test_raw_addnotes_action_only_in_anki_module():
    offenders = []
    for path in SRC.rglob("*.py"):
        if RAW_ACTION_RE.search(path.read_text(encoding="utf-8")) and path.name != "anki.py":
            offenders.append(path.name)
    assert not offenders, f'raw "addNotes" action used outside anki.py: {offenders}'
