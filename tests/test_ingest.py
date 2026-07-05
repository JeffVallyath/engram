import pytest

from engram.ingest import MAX_CHARS, IngestError, extract_text
from engram.models import DraftRequest
from engram.router import build_user_prompt


def test_txt_and_md_extract(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Title\nSome body text.", encoding="utf-8")
    assert "Some body text" in extract_text(str(f))


def test_missing_file_raises(tmp_path):
    with pytest.raises(IngestError, match="not found"):
        extract_text(str(tmp_path / "nope.pdf"))


def test_unsupported_extension_raises(tmp_path):
    f = tmp_path / "deck.docx"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(IngestError, match="unsupported"):
        extract_text(str(f))


def test_oversized_file_raises(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * (MAX_CHARS + 1), encoding="utf-8")
    with pytest.raises(IngestError, match="limit"):
        extract_text(str(f))


def test_blank_pdf_raises(tmp_path):
    from pypdf import PdfWriter

    f = tmp_path / "blank.pdf"
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    with open(f, "wb") as fh:
        w.write(fh)
    with pytest.raises(IngestError, match="no extractable text"):
        extract_text(str(f))


def test_ingest_prompt_demands_coverage_within_budget():
    req = DraftRequest(
        knowledge_type="auto",
        selected_text="Abstract... Methods... Results... Discussion...",
        user_note="",
        window_title="paper.pdf",
        app_class="file",
        max_cards=12,
        ingest=True,
    )
    prompt = build_user_prompt(req)
    assert "ENTIRE DOCUMENT" in prompt
    assert "COVERAGE" in prompt
    assert "budget is 12" in prompt
    assert "omitted_targets" in prompt
    assert "BEGIN DOCUMENT" in prompt


def test_non_ingest_prompt_unchanged():
    req = DraftRequest(
        knowledge_type="auto", selected_text="a selection", user_note="",
        window_title="w", app_class="browser", max_cards=2,
    )
    assert "ENTIRE DOCUMENT" not in build_user_prompt(req)
