# engram cookie bridge (Chrome extension)

Lets engram ingest login-gated lecture videos (Canvas / Panopto / Kaltura /
Echo360) **without** exporting a cookies.txt.

Modern Chrome on Windows app-bound-encrypts its cookie database and locks it
while running, so no external tool — yt-dlp included — can read it. Only code
running *inside* Chrome can. This tiny extension does exactly that: for the
sites you choose to track, it sends their cookies to the engram app on
`127.0.0.1` (loopback, never off-box), and only for those sites.

## One-time setup

1. Make sure engram is running (the cookie receiver starts with it; port
   `8766` by default — see `[ingest] cookie_bridge_port` in
   `~/.engram/config.toml`).
2. In Chrome, open `chrome://extensions`, turn on **Developer mode** (top
   right), click **Load unpacked**, and select this `extension/` folder.
3. Open your Canvas/Panopto video page, click the engram extension icon, and
   hit **Track this site**. That's it — one click per platform, ever.

From then on, whenever you're logged in, the extension keeps engram's cookies
fresh automatically (on login, on cookie refresh, and every 30 min). Paste the
video link into engram's "Ingest a video link…" and it just works.

## What is and isn't sent

- **Sent:** cookies for the domains you explicitly track, to `127.0.0.1` only.
- **Never sent:** cookies for any other site; nothing leaves your machine.
- engram stores them at `~/.engram/cookies.json` and hands yt-dlp only the
  cookies for the specific URL being ingested, via a temp file it deletes right
  after.

## If a sync fails

The popup shows the last sync result. "engram not reachable" means engram isn't
running or the port differs — start engram, or match `cookie_bridge_port`.
