import pytest

from engram import transcript
from engram.ingest import IngestError, load_source
from engram.transcript import (
    TranscriptResult,
    extract_video_id,
    fetch_transcript,
    format_transcript,
    is_video_url,
)

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=90s",
    f"https://www.youtube.com/watch?list=PLx&v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=abc123",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
    f"https://www.youtube.com/embed/{VID}",
    f"www.youtube.com/watch?v={VID}",  # no scheme
    f"  https://youtu.be/{VID}  ",  # stray whitespace
])
def test_video_id_extracted(url):
    assert extract_video_id(url) == VID


@pytest.mark.parametrize("source", [
    "https://www.google.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/channel/UCabc",
    "https://www.youtube.com/watch?v=tooshort",
    "https://vimeo.com/123456789",
    "C:/papers/attention.pdf",
    "just some text",
])
def test_non_video_sources_rejected(source):
    assert extract_video_id(source) is None
    assert not is_video_url(source)


def test_format_groups_by_minute_with_stamps():
    text = format_transcript([
        ("so today we're going to", 0.0),
        ("talk about spaced repetition", 3.2),
        ("the forgetting curve says", 61.5),
        ("retention decays exponentially", 65.0),
    ])
    lines = text.splitlines()
    assert lines[0] == "[0:00] so today we're going to talk about spaced repetition"
    assert lines[1] == "[1:01] the forgetting curve says retention decays exponentially"


def test_format_skips_stage_directions_and_flattens_newlines():
    text = format_transcript([
        ("[Music]", 0.0),
        ("welcome\nback", 2.0),
        ("[Applause]", 5.0),
    ])
    assert text == "[0:02] welcome back"


def test_format_hour_stamp():
    text = format_transcript([("closing thoughts", 3725.0)])
    assert text.startswith("[1:02:05]")


def test_fetch_transcript_happy_path(monkeypatch):
    monkeypatch.setattr(transcript, "_fetch_snippets",
                        lambda vid: [("interleaving beats blocking", 12.0)])
    monkeypatch.setattr(transcript, "_fetch_title", lambda vid: "Learning Science 101")
    r = fetch_transcript(f"https://youtu.be/{VID}")
    assert isinstance(r, TranscriptResult)
    assert r.video_id == VID
    assert r.title == "Learning Science 101"
    assert "[0:12] interleaving beats blocking" in r.text


def test_fetch_transcript_bad_url_raises():
    with pytest.raises(IngestError, match="not a recognizable YouTube link"):
        fetch_transcript("https://example.com/video")


def test_fetch_transcript_empty_raises(monkeypatch):
    monkeypatch.setattr(transcript, "_fetch_snippets", lambda vid: [("[Music]", 0.0)])
    with pytest.raises(IngestError, match="empty"):
        fetch_transcript(f"https://youtu.be/{VID}")


def test_fetch_transcript_oversized_raises(monkeypatch):
    monkeypatch.setattr(transcript, "_fetch_snippets",
                        lambda vid: [("x" * 500, float(i)) for i in range(1000)])
    with pytest.raises(IngestError, match="limit"):
        fetch_transcript(f"https://youtu.be/{VID}")


def test_load_source_routes_video_url(monkeypatch):
    monkeypatch.setattr(transcript, "_fetch_snippets", lambda vid: [("hello", 0.0)])
    monkeypatch.setattr(transcript, "_fetch_title", lambda vid: "A Talk")
    text, name = load_source(f"https://www.youtube.com/watch?v={VID}")
    assert name == "A Talk"
    assert "hello" in text


def test_load_source_rejects_non_youtube_url():
    with pytest.raises(IngestError, match="only YouTube links"):
        load_source("https://example.com/article")


def test_load_source_routes_file_path(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("spacing beats cramming", encoding="utf-8")
    text, name = load_source(str(f))
    assert name == "notes.md"
    assert "spacing beats cramming" in text
