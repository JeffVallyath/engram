"""Cookie bridge: a loopback receiver that a companion Chrome extension pushes
cookies into, so gated video ingest (Canvas/Panopto/Kaltura) works without a
manual cookies.txt.

Why this exists: Chrome on Windows app-bound-encrypts its cookie DB and locks
it while running, so no external process (yt-dlp included) can read it. Only
code running INSIDE Chrome can — an extension, via chrome.cookies. The
extension POSTs cookies for the domains you choose to 127.0.0.1; engram keeps
them here and hands yt-dlp just the ones a given URL needs.

Security stance: bound to loopback only, receive-only (no endpoint that hands
cookies back out), and only the domains you track in the extension are ever
sent — not your whole jar.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import CONFIG_DIR

log = logging.getLogger(__name__)

COOKIE_STORE = CONFIG_DIR / "cookies.json"
MAX_BODY = 4 * 1024 * 1024  # a few MB of cookies is already absurd


def save_cookies(payload: dict, store: Path | None = None) -> int:
    """Persist an extension push. Returns the cookie count stored."""
    store = store or COOKIE_STORE
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        raise ValueError("payload has no 'cookies' list")
    clean = [_normalize(c) for c in cookies if isinstance(c, dict) and c.get("name")]
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean), encoding="utf-8")
    tmp.replace(store)
    return len(clean)


def _normalize(c: dict) -> dict:
    # keep only the fields a Netscape line needs; a chrome.cookies.Cookie has
    # domain/name/value/path/secure/hostOnly/expirationDate
    return {
        "domain": str(c.get("domain", "")),
        "name": str(c.get("name", "")),
        "value": str(c.get("value", "")),
        "path": str(c.get("path", "/")) or "/",
        "secure": bool(c.get("secure", False)),
        "hostOnly": bool(c.get("hostOnly", False)),
        "expires": int(c.get("expirationDate", 0) or 0),
    }


def load_cookies(store: Path | None = None) -> list[dict]:
    store = store or COOKIE_STORE
    if not store.exists():
        return []
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _host_matches(cookie_domain: str, host: str) -> bool:
    d = cookie_domain.lstrip(".").lower()
    host = host.lower()
    return bool(d) and (host == d or host.endswith("." + d))


def cookies_for_host(cookies: list[dict], host: str) -> list[dict]:
    return [c for c in cookies if _host_matches(c.get("domain", ""), host)]


def write_netscape(cookies: list[dict], fh) -> int:
    """Write cookies in Netscape cookies.txt format (what yt-dlp reads).
    Returns the number written."""
    fh.write("# Netscape HTTP Cookie File\n")
    n = 0
    for c in cookies:
        domain = c.get("domain", "")
        host_only = c.get("hostOnly", False) or not domain.startswith(".")
        include_sub = "FALSE" if host_only else "TRUE"
        dfield = domain if domain.startswith(".") or host_only else "." + domain
        row = [
            dfield,
            include_sub,
            c.get("path", "/") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(int(c.get("expires", 0) or 0)),
            c.get("name", ""),
            c.get("value", ""),
        ]
        fh.write("\t".join(row) + "\n")
        n += 1
    return n


class _Handler(BaseHTTPRequestHandler):
    def _deny(self, code, msg):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(msg.encode())

    def do_POST(self):
        # loopback only — never accept a cookie push from off-box
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self._deny(403, "loopback only")
        if self.path != "/cookies":
            return self._deny(404, "not found")
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._deny(400, "bad length")
        if length <= 0 or length > MAX_BODY:
            return self._deny(413, "bad body size")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            count = save_cookies(payload)
        except (ValueError, UnicodeDecodeError) as e:
            return self._deny(400, f"bad payload: {e}")
        log.info("cookie bridge: stored %d cookies from extension", count)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "stored": count}).encode())

    def log_message(self, *_a):  # silence the default stderr access log
        pass


def start_cookie_server(port: int) -> ThreadingHTTPServer | None:
    """Start the loopback cookie receiver in a daemon thread. Returns the
    server (or None if the port was busy — a non-fatal degradation)."""
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError as e:
        log.warning("cookie bridge disabled — could not bind 127.0.0.1:%d (%s)", port, e)
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("cookie bridge listening on 127.0.0.1:%d", port)
    return srv
