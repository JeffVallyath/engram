"""File ingest: pull text out of a pdf/txt/md so the whole document can be
drafted into a small, coverage-oriented card set (still budgeted, still
approval-gated — a paper gets 12 cards by default, not 120)."""

from __future__ import annotations

from pathlib import Path

MAX_CHARS = 400_000  # roughly 100k tokens, far under the model limit but
                     # way past the point where a "card set" makes sense
DEFAULT_BUDGET = 12
BUDGET_LIMIT = 30


class IngestError(Exception):
    pass


def extract_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise IngestError(f"file not found: {p}")

    ext = p.suffix.lower()
    if ext in (".txt", ".md"):
        text = p.read_text(encoding="utf-8", errors="replace")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise IngestError('pdf ingest needs the "pypdf" package: pip install pypdf') from e
        reader = PdfReader(str(p))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raise IngestError(f"unsupported file type {ext!r} — use .pdf, .txt or .md")

    if not text.strip():
        raise IngestError(f"no extractable text in {p.name} (scanned/image-only pdf?)")
    if len(text) > MAX_CHARS:
        raise IngestError(
            f"{p.name} is {len(text):,} chars — over the {MAX_CHARS:,} limit. "
            f"Split it, or ingest the sections you actually care about."
        )
    return text
