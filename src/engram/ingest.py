"""File ingest: pull text out of a pdf/txt/md so the whole document can be
drafted into a small, coverage-oriented card set (still budgeted, still
approval-gated — a paper gets 12 cards by default, not 120)."""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

MAX_CHARS = 400_000  # roughly 100k tokens, far under the model limit but
                     # way past the point where a "card set" makes sense
DEFAULT_BUDGET = 12
BUDGET_LIMIT = 30

FILETYPES = [
    ("documents", "*.pdf *.docx *.txt *.md *.json *.csv *.htm *.html"),
    ("all files", "*.*"),
]


class IngestError(Exception):
    pass


def load_source(source: str) -> tuple[str, str]:
    """Route an ingest source (file path or YouTube link) to its extractor.

    Returns (text, display_name) — the name a human would recognize the
    source by: filename for files, video title for videos."""
    from .transcript import fetch_transcript, is_video_url

    if is_video_url(source):
        tr = fetch_transcript(source)
        return tr.text, tr.title
    if source.lower().startswith(("http://", "https://")):
        raise IngestError(
            "only YouTube links are supported for URL ingest — for other pages, "
            "save as html/pdf and ingest the file"
        )
    return extract_text(source), Path(source).name


def extract_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise IngestError(f"file not found: {p}")

    ext = p.suffix.lower()
    if ext in (".txt", ".md", ".json", ".csv"):
        text = p.read_text(encoding="utf-8", errors="replace")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise IngestError('pdf ingest needs the "pypdf" package: pip install pypdf') from e
        try:
            reader = PdfReader(str(p))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise IngestError(f"could not read {p.name} as a pdf: {e}") from e
    elif ext == ".docx":
        try:
            import docx
        except ImportError as e:
            raise IngestError('docx ingest needs the "python-docx" package: pip install python-docx') from e
        try:
            d = docx.Document(str(p))
            text = "\n".join(par.text for par in d.paragraphs)
        except Exception as e:
            raise IngestError(f"could not read {p.name} as a docx: {e}") from e
    elif ext in (".html", ".htm"):
        raw = p.read_text(encoding="utf-8", errors="replace")
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", raw))
    else:
        raise IngestError(
            f"unsupported file type {ext!r} — use pdf, docx, txt, md, json, csv or html"
        )

    if not text.strip():
        raise IngestError(f"no extractable text in {p.name} (scanned/image-only pdf?)")
    if len(text) > MAX_CHARS:
        raise IngestError(
            f"{p.name} is {len(text):,} chars — over the {MAX_CHARS:,} limit. "
            f"Split it, or ingest the sections you actually care about."
        )
    return text
