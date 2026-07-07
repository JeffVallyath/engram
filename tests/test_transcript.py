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


def test_fetch_transcript_non_url_raises():
    with pytest.raises(IngestError, match="not a video link"):
        fetch_transcript("C:/papers/attention.pdf")


def test_fetch_transcript_routes_non_youtube_urls_to_ytdlp(monkeypatch):
    seen = {}

    def fake_ytdlp(url, ingest_cfg=None):
        seen["url"] = url
        return [("welcome to the lecture", 4.0)], "Week 3 — Panopto"

    monkeypatch.setattr(transcript, "_ytdlp_captions", fake_ytdlp)
    r = fetch_transcript("https://uni.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=abc")
    assert seen["url"].startswith("https://uni.hosted.panopto.com")
    assert r.title == "Week 3 — Panopto"
    assert "[0:04] welcome to the lecture" in r.text
    assert r.video_id == ""


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


def test_load_source_routes_any_url_to_transcript(monkeypatch):
    monkeypatch.setattr(transcript, "_ytdlp_captions",
                        lambda url, ingest_cfg=None: ([("hi", 0.0)], "A Lecture"))
    text, name = load_source("https://vimeo.com/123456789")
    assert name == "A Lecture"
    assert "hi" in text


def test_load_source_routes_file_path(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("spacing beats cramming", encoding="utf-8")
    text, name = load_source(str(f))
    assert name == "notes.md"
    assert "spacing beats cramming" in text


VTT_SAMPLE = """WEBVTT
Kind: captions

00:00:01.000 --> 00:00:04.000
<c>welcome to</c> the course

00:00:04.000 --> 00:00:07.500
welcome to the course
today we cover graphs

1:00:02.250 --> 1:00:05.000
closing &amp; questions
"""


def test_parse_caption_file_vtt_with_rolling_dedupe():
    snippets = transcript.parse_caption_file(VTT_SAMPLE)
    texts = [t for t, _ in snippets]
    assert texts == ["welcome to the course", "today we cover graphs", "closing & questions"]
    assert snippets[0][1] == 1.0
    assert snippets[2][1] == 3602.25  # hour timestamps parse


def test_parse_caption_file_srt_commas():
    srt = "1\n00:00:02,500 --> 00:00:05,000\nhello there\n\n2\n00:00:05,000 --> 00:00:08,000\ngeneral kenobi\n"
    snippets = transcript.parse_caption_file(srt)
    assert snippets == [("hello there", 2.5), ("general kenobi", 5.0)]


def test_pick_caption_track_prefers_manual_english_vtt():
    info = {
        "subtitles": {
            "de": [{"ext": "vtt", "url": "http://x/de.vtt"}],
            "en": [{"ext": "json3", "url": "http://x/en.json3"},
                   {"ext": "vtt", "url": "http://x/en.vtt"}],
        },
        "automatic_captions": {"en": [{"ext": "vtt", "url": "http://x/auto.vtt"}]},
    }
    assert transcript._pick_caption_track(info) == "http://x/en.vtt"


def test_pick_caption_track_falls_back_to_auto_then_none():
    auto_only = {"automatic_captions": {"en": [{"ext": "vtt", "url": "http://x/auto.vtt"}]}}
    assert transcript._pick_caption_track(auto_only) == "http://x/auto.vtt"
    assert transcript._pick_caption_track({}) is None
    yt_internal_only = {"subtitles": {"en": [{"ext": "json3", "url": "http://x/en.json3"}]}}
    assert transcript._pick_caption_track(yt_internal_only) is None


def test_hls_caption_playlist_is_stitched():
    manifest = "#EXTM3U\n#EXT-X-VERSION:4\n#EXTINF:30.0,\nen.vtt?segment=0\n#EXTINF:30.0,\nen.vtt?segment=1\n"

    class FakeYdl:
        def __init__(self):
            self.fetched = []

        def urlopen(self, u):
            self.fetched.append(u)
            seg = u[-1]
            body = f"WEBVTT\n\n00:00:0{seg}.000 --> 00:00:05.000\nsegment {seg} text\n"

            class R:
                def read(self_inner):
                    return body.encode()
            return R()

    ydl = FakeYdl()
    data = transcript._fetch_hls_segments(manifest, "https://hls.example.com/subs/en.m3u8", ydl)
    assert ydl.fetched == [
        "https://hls.example.com/subs/en.vtt?segment=0",
        "https://hls.example.com/subs/en.vtt?segment=1",
    ]
    snippets = transcript.parse_caption_file(data)
    assert [t for t, _ in snippets] == ["segment 0 text", "segment 1 text"]


UCSC = "https://media.ucsc.edu/V/Video?isPlaying=false&v=2073423&a=1855346453&classPID=2361663&cim=true"


def test_yuja_params_parsed():
    scheme, host, v, a = transcript.yuja_params(UCSC)
    assert (scheme, host, v, a) == ("https", "media.ucsc.edu", "2073423", "1855346453")


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://uni.hosted.panopto.com/Panopto/Pages/Viewer.aspx?id=abc",
    "https://media.ucsc.edu/V/Video?foo=bar",  # no v= id
])
def test_yuja_params_rejects_non_yuja(url):
    assert transcript.yuja_params(url) is None


def test_find_caption_link_walks_nested_json():
    data = {"video": {"captionFileLink": "/P/Data/Caption/abc.vtt", "captionPID": 99},
            "title": "Lecture 1"}
    assert transcript._find_caption_link(data) == "/P/Data/Caption/abc.vtt"


def test_find_caption_link_prefers_vtt_over_other():
    data = {"transcriptDownload": "/x/t.pdf", "captionFileLink": "/x/c.srt"}
    assert transcript._find_caption_link(data).endswith(".srt")


def test_find_caption_link_none_when_absent():
    assert transcript._find_caption_link({"title": "x", "duration": 10}) is None


def test_yuja_captions_end_to_end(monkeypatch):
    from engram import cookie_bridge
    monkeypatch.setattr(cookie_bridge, "load_cookies",
                        lambda store=None: [{"domain": "media.ucsc.edu", "name": "s",
                                             "value": "tok", "path": "/", "secure": True,
                                             "hostOnly": True, "expires": 0}])
    seen = {}

    def fake_json(base, v, a, cookies):
        seen["base"], seen["v"], seen["a"], seen["cookies"] = base, v, a, cookies
        return {"title": "CC - Lecture Fodor 1", "captionFileLink": "/P/Data/Caption/xol.vtt"}

    def fake_text(url, cookies):
        seen["caption_url"] = url
        return "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nsystematicity matters\n"

    monkeypatch.setattr(transcript, "_yuja_fetch_json", fake_json)
    monkeypatch.setattr(transcript, "_yuja_fetch_text", fake_text)

    r = fetch_transcript(UCSC)
    assert seen["v"] == "2073423" and seen["a"] == "1855346453"
    assert seen["cookies"] == {"s": "tok"}
    assert seen["caption_url"] == "https://media.ucsc.edu/P/Data/Caption/xol.vtt"
    assert r.title == "CC - Lecture Fodor 1"
    assert "[0:01] systematicity matters" in r.text


def test_yuja_captions_no_cookies_raises(monkeypatch):
    from engram import cookie_bridge
    monkeypatch.setattr(cookie_bridge, "load_cookies", lambda store=None: [])
    with pytest.raises(IngestError, match="Track this site"):
        fetch_transcript(UCSC)
