import io
import json
import threading
import urllib.request

import pytest

from engram import cookie_bridge as cb


def sample(**over):
    base = dict(domain=".canvas.university.edu", name="sess", value="abc123",
                path="/", secure=True, hostOnly=False, expirationDate=1893456000)
    base.update(over)
    return base


def test_save_and_load_roundtrip(tmp_path):
    store = tmp_path / "cookies.json"
    n = cb.save_cookies({"cookies": [sample(), sample(name="csrf", value="z")]}, store)
    assert n == 2
    loaded = cb.load_cookies(store)
    assert {c["name"] for c in loaded} == {"sess", "csrf"}
    assert loaded[0]["expires"] == 1893456000  # expirationDate -> expires


def test_save_rejects_non_list(tmp_path):
    with pytest.raises(ValueError, match="cookies"):
        cb.save_cookies({"nope": 1}, tmp_path / "c.json")


def test_save_drops_nameless_entries(tmp_path):
    store = tmp_path / "c.json"
    n = cb.save_cookies({"cookies": [sample(), {"value": "x"}, "garbage"]}, store)
    assert n == 1


def test_load_missing_returns_empty(tmp_path):
    assert cb.load_cookies(tmp_path / "absent.json") == []


def test_cookies_for_host_matches_domain_and_subdomains():
    ck = [
        sample(domain=".canvas.university.edu", name="a"),
        sample(domain="panopto.university.edu", name="b", hostOnly=True),
        sample(domain=".othersite.com", name="c"),
    ]
    got = {c["name"] for c in cb.cookies_for_host(ck, "eu.canvas.university.edu")}
    assert got == {"a"}
    got2 = {c["name"] for c in cb.cookies_for_host(ck, "panopto.university.edu")}
    assert got2 == {"b"}
    assert cb.cookies_for_host(ck, "evil.com") == []


def test_write_netscape_format():
    buf = io.StringIO()
    n = cb.write_netscape([_norm(sample()), _norm(sample(name="csrf", value="z",
                                                          domain="host.edu", hostOnly=True))], buf)
    assert n == 2
    lines = [l for l in buf.getvalue().splitlines() if not l.startswith("#")]
    # dot-domain -> includeSubdomains TRUE; host-only -> FALSE and no leading dot
    assert lines[0].split("\t") == [".canvas.university.edu", "TRUE", "/", "TRUE",
                                    "1893456000", "sess", "abc123"]
    assert lines[1].split("\t")[0] == "host.edu"
    assert lines[1].split("\t")[1] == "FALSE"


def _norm(c):
    # mirror what save_cookies stores (expirationDate -> expires)
    d = dict(c)
    d["expires"] = int(d.pop("expirationDate", 0))
    return d


def test_server_receives_and_stores(tmp_path, monkeypatch):
    store = tmp_path / "cookies.json"
    monkeypatch.setattr(cb, "COOKIE_STORE", store)
    srv = cb.start_cookie_server(0)  # port 0 = any free port
    assert srv is not None
    try:
        port = srv.server_address[1]
        body = json.dumps({"cookies": [sample()]}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/cookies", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            resp = json.loads(r.read())
        assert resp == {"ok": True, "stored": 1}
        assert cb.load_cookies(store)[0]["name"] == "sess"
    finally:
        srv.shutdown()


def test_server_rejects_wrong_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "COOKIE_STORE", tmp_path / "c.json")
    srv = cb.start_cookie_server(0)
    try:
        port = srv.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/other", data=b"{}")
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=3)
        assert ei.value.code == 404
    finally:
        srv.shutdown()
