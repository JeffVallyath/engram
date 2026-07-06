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
    f = tmp_path / "song.mp3"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(IngestError, match="unsupported"):
        extract_text(str(f))


def test_corrupt_docx_is_friendly_error(tmp_path):
    f = tmp_path / "broken.docx"
    f.write_text("this is not a real docx", encoding="utf-8")
    with pytest.raises(IngestError, match="could not read"):
        extract_text(str(f))


def test_oversized_file_raises(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("x" * (MAX_CHARS + 1), encoding="utf-8")
    with pytest.raises(IngestError, match="limit"):
        extract_text(str(f))


def test_docx_extract(tmp_path):
    import docx

    f = tmp_path / "doc.docx"
    d = docx.Document()
    d.add_paragraph("Interleaving beats blocking for confusable categories.")
    d.save(str(f))
    assert "confusable categories" in extract_text(str(f))


def test_json_and_csv_read_as_text(tmp_path):
    j = tmp_path / "data.json"
    j.write_text('{"effect": "interleaving"}', encoding="utf-8")
    assert "interleaving" in extract_text(str(j))
    c = tmp_path / "data.csv"
    c.write_text("condition,accuracy\ninterleaved,72.4\n", encoding="utf-8")
    assert "72.4" in extract_text(str(c))


def test_html_tags_stripped(tmp_path):
    f = tmp_path / "page.html"
    f.write_text(
        "<html><head><style>body{color:red}</style></head>"
        "<body><h1>Spacing &amp; interleaving</h1><script>alert(1)</script>"
        "<p>fight different problems.</p></body></html>",
        encoding="utf-8",
    )
    text = extract_text(str(f))
    assert "Spacing & interleaving" in text
    assert "fight different problems" in text
    assert "<p>" not in text and "alert(1)" not in text and "color:red" not in text


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


def test_prompt_parts_keep_note_out_of_source():
    # the source part must be identical across draft-more/revise (which only
    # change the note) or the anthropic cache prefix never hits
    from engram.router import build_user_prompt_parts

    def make(note):
        return DraftRequest(
            knowledge_type="auto", selected_text="Abstract... Results...",
            user_note=note, window_title="paper.pdf", app_class="file",
            max_cards=12, ingest=True,
        )

    src1, task1 = build_user_prompt_parts(make(""))
    src2, task2 = build_user_prompt_parts(make("Draft cards for these omitted targets: X; Y"))
    assert src1 == src2
    assert "omitted targets: X; Y" in task2 and "omitted targets: X; Y" not in src2
    assert "Abstract... Results..." in src1 and "Abstract... Results..." not in task1
    # single-string form is the two parts joined
    assert build_user_prompt(make("")) == f"{task1}\n\n{src1}"


def test_redraft_replaces_coverage_directive_and_keeps_source_stable():
    from dataclasses import replace as dc_replace

    from engram.router import build_user_prompt_parts

    req = DraftRequest(
        knowledge_type="auto", selected_text="Abstract... Results...",
        user_note="", window_title="paper.pdf", app_class="file",
        max_cards=30, ingest=True,
    )
    redraft = dc_replace(req, redraft_targets=("author of quote A", "book B"))

    src_full, task_full = build_user_prompt_parts(req)
    src_re, task_re = build_user_prompt_parts(redraft)

    # source part byte-identical, or the anthropic cache prefix never hits
    assert src_re == src_full
    # coverage pass replaced by the narrow redraft directive
    assert "REDRAFT OF OMITTED TARGETS" in task_re
    assert "COVERAGE" not in task_re
    assert "- author of quote A" in task_re and "- book B" in task_re
    assert "at most 2 cards" in task_re
    assert "set omitted_targets to []" in task_re
