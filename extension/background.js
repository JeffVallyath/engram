// engram cookie bridge — background worker.
//
// Sends cookies for the domains you track to the engram app running on
// 127.0.0.1. Only tracked domains are ever read or sent; nothing leaves the
// machine. Triggers: on a cookie change for a tracked domain, on a periodic
// alarm, and on demand from the popup.

const PORT = 8766; // must match ingest.cookie_bridge_port in engram config
const ENDPOINT = `http://127.0.0.1:${PORT}/cookies`;

async function trackedDomains() {
  const { domains } = await chrome.storage.local.get({ domains: [] });
  return domains;
}

// collect every cookie whose domain matches one of the tracked domains
async function collect() {
  const domains = await trackedDomains();
  const out = [];
  const seen = new Set();
  for (const d of domains) {
    const bare = d.replace(/^\./, "");
    // getAll(domain) matches the domain and its subdomains
    const cks = await chrome.cookies.getAll({ domain: bare });
    for (const c of cks) {
      const key = `${c.domain}|${c.path}|${c.name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(c);
    }
  }
  return out;
}

async function sync(reason) {
  const cookies = await collect();
  if (!cookies.length) return { ok: false, reason: "no cookies for tracked domains" };
  try {
    const r = await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookies, reason }),
    });
    const body = await r.json();
    await chrome.storage.local.set({ lastSync: { at: Date.now(), stored: body.stored, ok: true } });
    return { ok: true, stored: body.stored };
  } catch (e) {
    // engram not running / port closed — not fatal, we retry on the next trigger
    await chrome.storage.local.set({ lastSync: { at: Date.now(), ok: false, error: String(e) } });
    return { ok: false, reason: "engram not reachable on 127.0.0.1:" + PORT };
  }
}

// re-sync whenever a tracked domain's cookie changes (login, refresh, logout)
chrome.cookies.onChanged.addListener(async ({ cookie }) => {
  const domains = await trackedDomains();
  const dom = cookie.domain.replace(/^\./, "");
  if (domains.some((d) => { const b = d.replace(/^\./, ""); return dom === b || dom.endsWith("." + b); })) {
    sync("cookie-changed");
  }
});

chrome.alarms.create("resync", { periodInMinutes: 30 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "resync") sync("alarm"); });
chrome.runtime.onStartup.addListener(() => sync("startup"));
chrome.runtime.onInstalled.addListener(() => sync("installed"));

// popup asks us to sync now or add the current tab's domain
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    if (msg.cmd === "sync") reply(await sync("manual"));
    else if (msg.cmd === "collect-count") reply({ count: (await collect()).length });
    else reply({ ok: false });
  })();
  return true; // async reply
});
