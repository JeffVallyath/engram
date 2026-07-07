// engram cookie bridge — popup.

const $ = (id) => document.getElementById(id);

async function getDomains() {
  const { domains } = await chrome.storage.local.get({ domains: [] });
  return domains;
}
async function setDomains(domains) {
  await chrome.storage.local.set({ domains });
}

async function render() {
  const domains = await getDomains();
  const ul = $("domains");
  ul.innerHTML = "";
  if (!domains.length) {
    const li = document.createElement("li");
    li.className = "dim";
    li.textContent = "No sites tracked yet.";
    ul.appendChild(li);
  }
  for (const d of domains) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = d;
    const rm = document.createElement("button");
    rm.className = "rm";
    rm.textContent = "✕";
    rm.onclick = async () => { await setDomains((await getDomains()).filter((x) => x !== d)); render(); };
    li.append(span, rm);
    ul.appendChild(li);
  }
  const { lastSync } = await chrome.storage.local.get({ lastSync: null });
  if (lastSync) {
    $("status").textContent = lastSync.ok
      ? `Last sync: ${lastSync.stored} cookies sent.`
      : `Last sync failed: ${lastSync.error || "engram not reachable"}.`;
  }
}

function currentHost() {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      try { resolve(new URL(tabs[0].url).hostname); } catch { resolve(null); }
    });
  });
}

// register the current site by its registrable-ish domain: drop the leftmost
// label so eu.canvas.uni.edu -> canvas.uni.edu (covers subdomains via getAll)
function toTrackable(host) {
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  // keep last 3 labels for typical uni hosts (canvas.uni.edu / panopto.uni.edu)
  return parts.slice(-3).join(".");
}

$("track").onclick = async () => {
  const host = await currentHost();
  if (!host) { $("status").textContent = "No site in the active tab."; return; }
  const dom = toTrackable(host);
  const domains = await getDomains();
  if (!domains.includes(dom)) { domains.push(dom); await setDomains(domains); }
  await render();
  chrome.runtime.sendMessage({ cmd: "sync" }, (res) => {
    $("status").textContent = res && res.ok
      ? `Tracking ${dom} — ${res.stored} cookies sent.`
      : `Tracking ${dom} — ${(res && res.reason) || "engram not reachable"}.`;
  });
};

$("sync").onclick = () => {
  chrome.runtime.sendMessage({ cmd: "sync" }, (res) => {
    $("status").textContent = res && res.ok
      ? `Synced ${res.stored} cookies.`
      : `Sync failed: ${(res && res.reason) || "engram not reachable"}.`;
  });
};

render();
