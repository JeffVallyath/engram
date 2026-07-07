"""Video ingest: turn a video link into transcript text so a talk/lecture
can be drafted into the same budgeted, approval-gated card set as a file.

Two paths, captioned videos only (no download, no audio transcription — a
caption-less video is a clean IngestError, not a Whisper pipeline... yet):
- YouTube links: youtube-transcript-api, no page scrape needed.
- Everything else (Canvas/Panopto/Kaltura/Echo360/Vimeo/...): yt-dlp reads
  the page and hands us its caption track; login-gated platforms work via
  [ingest] cookies_from_browser / cookies_file in the config.
"""

from __future__ import annotations

import html
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


_CUE_TS = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")


def parse_caption_file(data: str) -> list[tuple[str, float]]:
    """Parse a WebVTT or SRT caption file into (text, start_seconds) snippets.

    Handles the rolling-window style of machine captions (each cue repeats
    the previous line plus the new one) by dropping repeated lines."""
    snippets: list[tuple[str, float]] = []
    last_line = ""
    for block in re.split(r"\n\s*\n", data):
        lines = block.strip().splitlines()
        for i, line in enumerate(lines):
            if "-->" not in line:
                continue
            m = _CUE_TS.search(line.split("-->")[0])
            if not m:
                break
            h, mi, s, ms = (int(g or 0) for g in m.groups())
            start = h * 3600 + mi * 60 + s + ms / 1000
            for raw in lines[i + 1:]:
                text = html.unescape(re.sub(r"<[^>]+>", "", raw))
                text = " ".join(text.split())
                if text and text != last_line:
                    snippets.append((text, start))
                    last_line = text
            break
    return snippets


def _pick_caption_track(info: dict):
    """Choose a caption track URL from a yt-dlp info dict: manual subs beat
    auto captions, English beats other languages, vtt/srt beat exotic formats."""
    for tracks in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for lang in sorted(tracks, key=lambda l: (not l.lower().startswith("en"), l)):
            fmts = tracks[lang]
            for want in ("vtt", "srt"):
                for f in fmts:
                    if f.get("ext") == want and f.get("url"):
                        return f["url"]
            for f in fmts:
                if f.get("ext") in ("srv3", "srv2", "srv1", "json3"):
                    continue  # youtube-internal formats our parser doesn't read
                if f.get("url"):
                    return f["url"]
    return None


def _fetch_hls_segments(manifest: str, manifest_url: str, ydl) -> str:
    """Streaming platforms (TED, some Panopto/Kaltura) serve the caption
    "file" as an HLS playlist of short VTT segments — fetch and stitch."""
    from urllib.parse import urljoin

    segments = [ln.strip() for ln in manifest.splitlines()
                if ln.strip() and not ln.startswith("#")]
    if len(segments) > 1000:  # ~8h of 30s segments; something is wrong
        raise IngestError(f"caption playlist has {len(segments)} segments — refusing")
    parts = [ydl.urlopen(urljoin(manifest_url, seg)).read().decode("utf-8", "replace")
             for seg in segments]
    return "\n\n".join(parts)


def _bridge_cookie_file(url: str) -> str | None:
    """If the companion extension has pushed cookies covering this URL's host,
    write them to a temp Netscape file and return its path (caller deletes)."""
    import tempfile
    from urllib.parse import urlparse

    from . import cookie_bridge

    host = urlparse(url).hostname or ""
    matching = cookie_bridge.cookies_for_host(cookie_bridge.load_cookies(), host)
    if not matching:
        return None
    fd, path = tempfile.mkstemp(prefix="engram_ck_", suffix=".txt")
    with __import__("os").fdopen(fd, "w", encoding="utf-8") as fh:
        cookie_bridge.write_netscape(matching, fh)
    return path


def _ytdlp_captions(url: str, ingest_cfg=None) -> tuple[list[tuple[str, float]], str]:
    """(snippets, title) for a non-YouTube video page, via yt-dlp."""
    import os

    try:
        import yt_dlp
    except ImportError as e:
        raise IngestError(
            'ingesting non-YouTube video links needs the "yt-dlp" package: '
            "pip install yt-dlp"
        ) from e

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    # priority: bridge cookies (the only thing that works with modern Chrome)
    # > explicit cookies_file > cookies_from_browser
    bridge_file = _bridge_cookie_file(url)
    if bridge_file:
        opts["cookiefile"] = bridge_file
    elif ingest_cfg is not None and ingest_cfg.cookies_file:
        opts["cookiefile"] = ingest_cfg.cookies_file
    elif ingest_cfg is not None and ingest_cfg.cookies_from_browser:
        opts["cookiesfrombrowser"] = (ingest_cfg.cookies_from_browser,)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist":
                entries = [e for e in (info.get("entries") or []) if e]
                if len(entries) != 1:
                    raise IngestError(
                        f"that link is a collection of {len(entries)} videos — "
                        "ingest one video at a time"
                    )
                info = entries[0]
            title = info.get("title") or url
            track_url = _pick_caption_track(info)
            if track_url is None:
                raise IngestError(
                    f'no captions found on "{title}" — caption-less video needs '
                    "the Whisper path, which isn't wired up yet"
                )
            # ydl.urlopen reuses yt-dlp's cookie/session state, which a gated
            # platform may require for the caption file too
            data = ydl.urlopen(track_url).read().decode("utf-8", "replace")
            if data.lstrip().startswith("#EXTM3U"):
                data = _fetch_hls_segments(data, track_url, ydl)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).replace("ERROR: ", "").strip()
        if "logged in" in msg.lower() or "login" in msg.lower() or "401" in msg or "403" in msg:
            hint = (" — this platform needs a login. Track its domain in the engram "
                    "cookie-bridge extension") if not bridge_file else \
                   " — the tracked cookies may have expired; re-open the site in Chrome"
            msg += hint
        raise IngestError(f"could not read that video page: {msg}") from e
    finally:
        if bridge_file:
            try:
                os.remove(bridge_file)
            except OSError:
                pass
    return parse_caption_file(data), title


# --- YuJa (Lumina) — the platform UCSC and many campuses run; yt-dlp has no
# extractor for it. The player loads captions via a POST to /P/Data/VideoJSON
# (params video=<v>, a=<authCode> from the ?v=&a= URL); the JSON carries a
# caption file link, which we then download with the same session cookies. All
# reverse-engineered from the public Video.controller.js. Needs the video
# host's cookies from the bridge (track e.g. media.ucsc.edu in the extension).

def yuja_host(url: str):
    """(scheme, host) if this is a YuJa video URL (any /V/Video link), else
    None. Detection is path-only so ANY YuJa link works — the v/a codes get
    resolved from the page if they aren't in the URL."""
    from urllib.parse import urlparse

    u = urlparse(url)
    if "/V/Video" not in u.path:
        return None
    return u.scheme or "https", u.netloc


def _yuja_va_from_query(url: str):
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    return (q.get("v") or [None])[0], (q.get("a") or [""])[0]


def _yuja_va_from_page(page_html: str):
    """Pull the video id (v) and auth code (a) out of a YuJa page. The player
    embeds the canonical link (with ?v=&a=) in canonical/og:url/twitter:url
    meta tags even when the address-bar URL only carries a ?u= id."""
    from urllib.parse import parse_qs, urlparse

    for m in re.finditer(r'(?:href|content)="([^"]*?/V/Video\?[^"]*)"', page_html):
        q = parse_qs(urlparse(html.unescape(m.group(1))).query)
        v = (q.get("v") or [None])[0]
        if v:
            return v, (q.get("a") or [""])[0]
    return None, ""


def _requests_cookies_for(host: str) -> dict:
    from . import cookie_bridge

    return {c["name"]: c["value"]
            for c in cookie_bridge.cookies_for_host(cookie_bridge.load_cookies(), host)}


def _find_caption_link(obj) -> str | None:
    """Walk the VideoJSON response for a caption/transcript file URL. Defensive
    about the exact shape (the field is captionFileLink, but nesting varies)."""
    hits: list[str] = []

    def walk(o):
        if isinstance(o, dict):
            for k, val in o.items():
                if (isinstance(val, str) and val
                        and ("caption" in k.lower() or "transcript" in k.lower())
                        and ("/" in val or val.lower().endswith((".vtt", ".srt")))):
                    hits.append(val)
                walk(val)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    # prefer a vtt/srt link if several turned up
    hits.sort(key=lambda s: (not s.lower().endswith((".vtt", ".srt")), len(s)))
    return hits[0] if hits else None


def _yuja_fetch_json(base: str, v: str, a: str, cookies: dict) -> dict:
    import requests

    r = requests.post(f"{base}/P/Data/VideoJSON", data={"video": v, "a": a},
                      cookies=cookies, timeout=20,
                      headers={"X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    return r.json()


def _yuja_fetch_text(url: str, cookies: dict) -> str:
    import requests

    r = requests.get(url, cookies=cookies, timeout=20)
    r.raise_for_status()
    return r.text


def _yuja_captions(url: str) -> tuple[list[tuple[str, float]], str]:
    import logging
    from urllib.parse import urljoin

    import requests

    scheme, host = yuja_host(url)
    base = f"{scheme}://{host}"
    cookies = _requests_cookies_for(host)
    if not cookies:
        raise IngestError(
            f"no synced cookies for {host} — open the video in Chrome, click the "
            "engram cookie-bridge extension, and 'Track this site', then retry"
        )

    # v/a straight from the URL if present; otherwise fetch the page (which
    # every YuJa link renders) and read them from its embedded canonical link
    v, a = _yuja_va_from_query(url)
    if not v:
        try:
            page = _yuja_fetch_text(url, cookies)
        except requests.RequestException as e:
            raise IngestError(f"could not open the YuJa page {host}: {e}") from e
        v, a = _yuja_va_from_page(page)
        if not v:
            raise IngestError(
                f"couldn't find a video id on that {host} page — make sure you're "
                "logged in, or use the player's 'Copy Link' button"
            )

    try:
        data = _yuja_fetch_json(base, v, a, cookies)
    except (requests.RequestException, ValueError) as e:
        raise IngestError(f"YuJa metadata request failed for video {v}: {e}") from e

    logging.getLogger(__name__).info("yuja VideoJSON keys: %s",
                                     list(data)[:20] if isinstance(data, dict) else type(data))
    link = _find_caption_link(data)
    if not link:
        raise IngestError(
            f"YuJa returned no caption link for video {v} — the lecture may have no "
            "captions, or the response shape changed (see engram.log for its keys)"
        )
    caption_url = urljoin(base + "/", link)
    title = (data.get("title") or data.get("name") or f"YuJa video {v}") if isinstance(data, dict) else f"YuJa video {v}"
    try:
        text = _yuja_fetch_text(caption_url, cookies)
    except requests.RequestException as e:
        raise IngestError(f"could not download YuJa caption file: {e}") from e
    return parse_caption_file(text), title


def fetch_transcript(url: str, ingest_cfg=None) -> TranscriptResult:
    video_id = extract_video_id(url)
    if video_id is not None:
        snippets, title = _fetch_snippets(video_id), None
    elif yuja_host(url) is not None:
        snippets, title = _yuja_captions(url)
    elif url.lower().startswith(("http://", "https://")):
        snippets, title = _ytdlp_captions(url, ingest_cfg)
    else:
        raise IngestError(f"not a video link: {url!r}")

    text = format_transcript(snippets)
    if not text.strip():
        raise IngestError(f"transcript for {url} is empty")
    if len(text) > MAX_CHARS:
        raise IngestError(
            f"transcript is {len(text):,} chars — over the {MAX_CHARS:,} limit. "
            "Ingest a shorter video, or grab the section you care about as text."
        )
    if title is None:
        title = _fetch_title(video_id)
    return TranscriptResult(text=text, title=title, video_id=video_id or "")
