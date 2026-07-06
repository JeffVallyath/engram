"""Video ingest: turn a YouTube link into transcript text so a talk/lecture
can be drafted into the same budgeted, approval-gated card set as a file.

Captioned videos only (manual or auto-generated) — no download, no audio
transcription. A caption-less video is a clean IngestError, not a Whisper
pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ingest import MAX_CHARS, IngestError

# a coarse [m:ss] marker at the start of each ~60s block, so cards can cite
# roughly where in the video a claim came from
MARKER_EVERY_S = 60

_ID = r"[A-Za-z0-9_-]{11}"
_PATTERNS = [
    re.compile(rf"youtu\.be/({_ID})(?:[?&#/]|$)"),
    re.compile(rf"youtube\.com/watch\?[^#]*?\bv=({_ID})(?:[?&#]|$)"),
    re.compile(rf"youtube\.com/(?:shorts|live|embed)/({_ID})(?:[?&#/]|$)"),
]


@dataclass
class TranscriptResult:
    text: str
    title: str
    video_id: str


def extract_video_id(url: str) -> str | None:
    for pat in _PATTERNS:
        m = pat.search(url.strip())
        if m:
            return m.group(1)
    return None


def is_video_url(source: str) -> bool:
    return extract_video_id(source) is not None


def format_transcript(snippets: list[tuple[str, float]]) -> str:
    """Join (text, start_seconds) caption snippets into marked-up blocks."""
    blocks: list[tuple[str, list[str]]] = []  # (stamp, texts)
    current_block = -1
    for text, start in snippets:
        text = " ".join(text.split())  # captions embed newlines
        # stage directions like [Music]/[Applause] carry nothing cardable
        if not text or (text.startswith("[") and text.endswith("]")):
            continue
        b = int(start // MARKER_EVERY_S)
        if b != current_block or not blocks:
            current_block = b
            m, s = divmod(int(start), 60)
            h, m = divmod(m, 60)
            stamp = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            blocks.append((stamp, []))
        blocks[-1][1].append(text)
    return "\n".join(f"[{stamp}] {' '.join(texts)}" for stamp, texts in blocks if texts)


def _fetch_snippets(video_id: str) -> list[tuple[str, float]]:
    try:
        from youtube_transcript_api import (
            CouldNotRetrieveTranscript,
            NoTranscriptFound,
            TranscriptsDisabled,
            VideoUnavailable,
            YouTubeTranscriptApi,
        )
    except ImportError as e:
        raise IngestError(
            'video ingest needs the "youtube-transcript-api" package: '
            "pip install youtube-transcript-api"
        ) from e

    import requests

    try:
        listing = YouTubeTranscriptApi().list(video_id)
        try:
            transcript = listing.find_transcript(["en"])
        except NoTranscriptFound:
            transcript = next(iter(listing), None)
            if transcript is None:
                raise
        fetched = transcript.fetch()
    except TranscriptsDisabled as e:
        raise IngestError(
            f"captions are disabled on video {video_id} — no transcript to ingest"
        ) from e
    except NoTranscriptFound as e:
        raise IngestError(f"no transcript available for video {video_id}") from e
    except VideoUnavailable as e:
        raise IngestError(
            f"video {video_id} is unavailable (private, deleted, or region-locked)"
        ) from e
    except CouldNotRetrieveTranscript as e:
        # covers IpBlocked/RequestBlocked/AgeRestricted/... — the library's
        # cause line says which; strip its multi-paragraph troubleshooting blurb
        cause = (getattr(e, "cause", "") or str(e)).strip().splitlines()[0]
        raise IngestError(f"could not fetch transcript for {video_id}: {cause}") from e
    except requests.RequestException as e:
        raise IngestError(f"network error fetching transcript: {e}") from e
    return [(s.text, s.start) for s in fetched]


def _fetch_title(video_id: str) -> str:
    # best-effort, keyless title lookup via oEmbed; the id is a fine fallback
    import requests

    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=5,
        )
        if r.ok:
            title = str(r.json().get("title", "")).strip()
            if title:
                return title
    except Exception:
        pass
    return f"youtube {video_id}"


def fetch_transcript(url: str) -> TranscriptResult:
    video_id = extract_video_id(url)
    if video_id is None:
        raise IngestError(
            f"not a recognizable YouTube link: {url!r} — expected a "
            "youtube.com/watch, youtu.be, shorts, live or embed URL"
        )
    text = format_transcript(_fetch_snippets(video_id))
    if not text.strip():
        raise IngestError(f"transcript for video {video_id} is empty")
    if len(text) > MAX_CHARS:
        raise IngestError(
            f"transcript is {len(text):,} chars — over the {MAX_CHARS:,} limit. "
            "Ingest a shorter video, or grab the section you care about as text."
        )
    return TranscriptResult(text=text, title=_fetch_title(video_id), video_id=video_id)
