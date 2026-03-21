// ── Config ────────────────────────────────────────────────────────────────────
const BACKEND_URL = "http://localhost:8000";

// ── State ────────────────────────────────────────────────────────────────────
let chatHistory  = [];
let currentUrl   = "";
let isLoading    = false;
let sessionLatestScan = null;

// ── DOM ───────────────────────────────────────────────────────────────────────
const messagesEl    = document.getElementById("messages");
const inputEl       = document.getElementById("chat-input");
const sendBtn       = document.getElementById("btn-send");
const clearBtn      = document.getElementById("btn-clear");
const urlDisplay    = document.getElementById("url-display");
const suggestionsEl = document.getElementById("suggestions");

// ── Boot ──────────────────────────────────────────────────────────────────────
async function init() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url) {
      currentUrl = tab.url;
      try { urlDisplay.textContent = new URL(tab.url).hostname; } catch (_) {}
    }
  } catch (_) {}

  try {
    if (currentUrl) {
      const domain = new URL(currentUrl).hostname;
      sessionLatestScan = await loadLatestScan(domain);
    }
  } catch (_) {}

  const stored = await chrome.storage.local.get(["chatHistory"]);
  if (stored.chatHistory?.length) {
    chatHistory = stored.chatHistory;
    chatHistory.forEach(m => appendBubble(m.role, m.content, null, true));
  } else {
    appendBubble("assistant",
      "👋 Hi! I'm **POST-deploy**.\n\n" +
      "I can scan this page for exposed secrets, or check if your site loads correctly from specific countries.\n\n" +
      "Try: **any api keys exposed?** · **check germany** · **safe to launch?**"
    );
  }
  scrollBottom();
}

// ── Storage ───────────────────────────────────────────────────────────────────
function todayKey(domain) {
  return `scan_${domain}_${new Date().toISOString().split("T")[0]}`;
}

async function saveScanResult(domain, data) {
  const key   = todayKey(domain);
  const entry = { ...data, ts: Date.now() };
  await chrome.storage.local.set({ [key]: entry });
  return entry;
}

async function loadLatestScan(domain) {
  const all  = await chrome.storage.local.get(null);
  const keys = Object.keys(all)
    .filter(k => k.startsWith(`scan_${domain}_`))
    .sort()
    .reverse();
  return keys[0] ? all[keys[0]] : null;
}

async function clearAllStorage() {
  const all  = await chrome.storage.local.get(null);
  const keysToRemove = Object.keys(all).filter(
    k => k === "chatHistory" || k.startsWith("scan_")
  );
  if (keysToRemove.length > 0) {
    await chrome.storage.local.remove(keysToRemove);
  }
}

function diffGhostFindings(prevScan, currentRawData) {
  if (!prevScan || !currentRawData) return null;
  const bFindings = prevScan?.ghostscan?.findings;
  const cFindings = currentRawData?.ghostscan?.findings;
  if (!Array.isArray(bFindings) || !Array.isArray(cFindings)) return null;
  if (prevScan?.ghostscan?.error) return null;

  const bSet  = new Set(bFindings.map(f => f.type));
  const cSet  = new Set(cFindings.map(f => f.type));
  const fixed = [...bSet].filter(t => !cSet.has(t));
  const added = [...cSet].filter(t => !bSet.has(t));
  const same  = [...cSet].filter(t =>  bSet.has(t));

  if (!fixed.length && !added.length && !same.length) return null;

  const daysAgo = prevScan.ts
    ? Math.max(1, Math.round((Date.now() - prevScan.ts) / 86400000))
    : "?";
  return { fixed, added, same, daysAgo };
}

// ── Markdown ──────────────────────────────────────────────────────────────────
function md(text) {
  return String(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}
function scrollBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

// ── Bubbles ───────────────────────────────────────────────────────────────────
function appendBubble(role, content, toolUsed = null, skipSave = false) {
  const wrap = document.createElement("div");
  wrap.className = `bubble ${role}`;

  if (role === "assistant" && toolUsed && !["off_topic","chat"].includes(toolUsed)) {
    const badge = document.createElement("div");
    badge.className = `tool-badge ${toolUsed}`;
    badge.textContent = {
      ghostscan: "🔒 GHOSTSCAN",
      geocheck:  "🌍 GEOCHECK",
      both:      "🔒🌍 FULL SCAN",
    }[toolUsed] || toolUsed;
    wrap.appendChild(badge);
  }

  const txt = document.createElement("div");
  txt.innerHTML = md(content);
  wrap.appendChild(txt);
  messagesEl.appendChild(wrap);
  scrollBottom();

  if (!skipSave && role !== "system") {
    chatHistory.push({ role, content });
    if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);
    chrome.storage.local.set({ chatHistory });
  }
  return wrap;
}

// ── Globe SVG (inline, used in both loaders) ──────────────────────────────────
function makeGlobeSvg(cls) {
  // Clean globe icon matching the style in the reference image
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("class", cls || "globe-spin");
  svg.innerHTML = `
    <circle cx="12" cy="12" r="10" stroke="#3b82f6" stroke-width="1.5"/>
    <ellipse cx="12" cy="12" rx="4" ry="10" stroke="#3b82f6" stroke-width="1.5"/>
    <line x1="2" y1="12" x2="22" y2="12" stroke="#3b82f6" stroke-width="1.5"/>
    <line x1="4.5" y1="6.5" x2="19.5" y2="6.5" stroke="#3b82f6" stroke-width="1"/>
    <line x1="4.5" y1="17.5" x2="19.5" y2="17.5" stroke="#3b82f6" stroke-width="1"/>
  `;
  return svg;
}

// ── Progress feed ─────────────────────────────────────────────────────────────
// mode: "ghost" | "geo"
// ghost → small globe + "Processing" label + step lines below
// geo   → larger globe + italic wait message, no step lines
function createProgressFeed(mode) {
  const wrap = document.createElement("div");
  wrap.className = "progress-feed";

  if (mode === "geo") {
    // ── Geo loader: spinning globe + italic text ─────────────────────
    const loader = document.createElement("div");
    loader.className = "geo-loader";

    loader.appendChild(makeGlobeSvg("globe-spin"));

    const textCol = document.createElement("div");
    textCol.className = "geo-loader-text";

    const label = document.createElement("div");
    label.className = "geo-loader-label";
    label.textContent = "This might take up to a minute…";

    const sub = document.createElement("div");
    sub.className = "geo-loader-sub";
    sub.textContent = "launching stealth browser";

    textCol.appendChild(label);
    textCol.appendChild(sub);
    loader.appendChild(textCol);
    wrap.appendChild(loader);

    messagesEl.appendChild(wrap);
    scrollBottom();

    return {
      el: wrap,
      // For geo mode, addLine just updates the sub-label text quietly
      async addLine(text) {
        sub.textContent = text.replace(/^[^\s]+\s/, "").toLowerCase();
        await new Promise(r => requestAnimationFrame(r));
      },
      markDone() {
        setTimeout(() => { wrap.style.opacity = "0.35"; }, 2000);
      },
      remove() { wrap.remove(); },
    };

  } else if (mode === "both") {
    // ── Full scan loader: globe + italic "entire scan takes 1-2 mins" ──
    const loader = document.createElement("div");
    loader.className = "geo-loader";

    loader.appendChild(makeGlobeSvg("globe-spin"));

    const textCol = document.createElement("div");
    textCol.className = "geo-loader-text";

    const label = document.createElement("div");
    label.className = "geo-loader-label";
    label.textContent = "Entire scan takes a minute or two…";

    const sub = document.createElement("div");
    sub.className = "geo-loader-sub";
    sub.textContent = "security + geo checks running";

    textCol.appendChild(label);
    textCol.appendChild(sub);
    loader.appendChild(textCol);
    wrap.appendChild(loader);

    messagesEl.appendChild(wrap);
    scrollBottom();

    return {
      el: wrap,
      async addLine(text) {
        sub.textContent = text.replace(/^[^\s]+\s/, "").toLowerCase();
        await new Promise(r => requestAnimationFrame(r));
      },
      markDone() {
        setTimeout(() => { wrap.style.opacity = "0.35"; }, 2000);
      },
      remove() { wrap.remove(); },
    };

  } else {
    // ── Ghost loader: small globe + "Processing" + step lines ────────
    const header = document.createElement("div");
    header.className = "pf-header";

    header.appendChild(makeGlobeSvg("globe-spin"));

    const title = document.createElement("div");
    title.className = "pf-title";
    title.textContent = "Processing";
    header.appendChild(title);
    wrap.appendChild(header);

    const linesEl = document.createElement("div");
    linesEl.className = "pf-lines";
    wrap.appendChild(linesEl);

    messagesEl.appendChild(wrap);
    scrollBottom();

    let lastLine = null;
    return {
      el: wrap,
      async addLine(text) {
        if (lastLine) lastLine.classList.remove("active");
        const line = document.createElement("div");
        line.className = "progress-line active";
        line.textContent = text;
        linesEl.appendChild(line);
        lastLine = line;
        scrollBottom();
        await new Promise(r => requestAnimationFrame(r));
      },
      markDone() {
        if (lastLine) lastLine.classList.remove("active");
        title.textContent = "Done";
        setTimeout(() => { wrap.style.opacity = "0.35"; }, 2000);
      },
      remove() { wrap.remove(); },
    };
  }
}

// ── Geo grid ──────────────────────────────────────────────────────────────────
function createGeoGrid(countries) {
  const grid = document.createElement("div");
  grid.className = "geo-grid";
  countries.forEach(c => {
    const item = document.createElement("div");
    item.className = "geo-item";
    item.innerHTML = `
      <div class="gi-top">
        <div class="geo-dot pending" id="dot-${c.code}"></div>
        <span>${c.flag} <span class="gi-name">${c.name}</span></span>
      </div>
      <div class="gi-meta" id="meta-${c.code}">
        <span class="gi-time" id="time-${c.code}">waiting…</span>
      </div>
      <div class="gi-details" id="details-${c.code}"></div>`;
    grid.appendChild(item);
  });
  return {
    el: grid,
    update(r) {
      const dot     = grid.querySelector(`#dot-${r.country}`);
      const time    = grid.querySelector(`#time-${r.country}`);
      const details = grid.querySelector(`#details-${r.country}`);

      if (dot) dot.className = `geo-dot ${r.status}`;
      if (time) time.textContent = r.load_time_ms ? `${r.load_time_ms}ms` : r.status;

      if (details) {
        let html = "";
        const statusCode = r.status_code ? `HTTP ${r.status_code}` : "";
        const lang       = r.page_language ? `lang: ${r.page_language}` : "";
        const metaLine   = [statusCode, lang].filter(Boolean).join("  ·  ");
        if (metaLine) html += `<div class="gi-meta-line">${metaLine}</div>`;

        if (r.cookie_banner_present) {
          const blocking = r.cookie_banner_blocking;
          const cbClass  = blocking ? "gi-tag gi-tag-warn" : "gi-tag gi-tag-info";
          const cbLabel  = blocking ? "🚫 Cookie banner blocking" : "🍪 Cookie banner present";
          html += `<div class="${cbClass}">${cbLabel}</div>`;
          if (r.cookie_banner_description) {
            html += `<div class="gi-cookie-desc">${r.cookie_banner_description.substring(0, 80)}…</div>`;
          }
        }

        if (r.geo_redirected) {
          html += `<div class="gi-tag gi-tag-warn">↪ Geo-redirected</div>`;
        }

        (r.legal_compliance_issues || []).forEach(issue => {
          html += `<div class="gi-legal">⚖️ ${issue.substring(0, 80)}</div>`;
        });

        (r.issues || [])
          .filter(i => !i.startsWith("Cookie") && !i.startsWith("Geo-redirect"))
          .forEach(issue => {
            html += `<div class="gi-issue">${issue.substring(0, 80)}</div>`;
          });

        details.innerHTML = html;
      }
      scrollBottom();
    },
  };
}

// ── Findings ──────────────────────────────────────────────────────────────────
function renderFindings(findings) {
  if (!findings?.length) return null;
  const list = document.createElement("div");
  list.className = "findings-list";
  const SEV = { CRITICAL:"🔴", HIGH:"🟠", WARNING:"🟡", INFO:"🟢" };

  findings.slice(0, 8).forEach(f => {
    const item = document.createElement("div");
    item.className = `finding-item ${f.severity}`;

    const header = document.createElement("div");
    header.className = "fi-header";
    const name = document.createElement("span");
    name.className = "fi-name";
    name.textContent = `${SEV[f.severity] || "⚪"} ${f.type}`;
    header.appendChild(name);

    if (f.value_preview && f.value_preview !== "****") {
      const copyBtn = document.createElement("button");
      copyBtn.className = "fi-copy-btn";
      copyBtn.textContent = "copy";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(f.value_preview);
          copyBtn.textContent = "✓";
          setTimeout(() => { copyBtn.textContent = "copy"; }, 1500);
        } catch (_) {}
      });
      header.appendChild(copyBtn);
    }
    item.appendChild(header);

    const loc = document.createElement("div");
    loc.className = "fi-loc";
    loc.textContent = f.location;
    item.appendChild(loc);

    if (f.value_preview) {
      const val = document.createElement("div");
      val.className = "fi-val";
      val.textContent = f.value_preview;
      item.appendChild(val);
    }

    if (f.fix) {
      const fixRow = document.createElement("div");
      fixRow.className = "fi-fix";
      fixRow.innerHTML = `<span class="fi-fix-icon">💡</span><span>${f.fix}</span>`;
      item.appendChild(fixRow);
    }

    list.appendChild(item);
  });
  return list;
}

// ── Diff ──────────────────────────────────────────────────────────────────────
function renderDiff(diff) {
  if (!diff) return null;
  const block = document.createElement("div");
  block.className = "diff-block";
  block.innerHTML = `<div class="diff-title">vs. scan ${diff.daysAgo} day(s) ago</div>`;
  diff.fixed.forEach(t => {
    const d = document.createElement("div");
    d.className = "diff-fixed";
    d.textContent = `✅ Fixed: ${t}`;
    block.appendChild(d);
  });
  diff.added.forEach(t => {
    const d = document.createElement("div");
    d.className = "diff-new";
    d.textContent = `🆕 New: ${t}`;
    block.appendChild(d);
  });
  diff.same.forEach(t => {
    const d = document.createElement("div");
    d.className = "diff-same";
    d.textContent = `🔄 Still present: ${t}`;
    block.appendChild(d);
  });
  return block;
}

// ── Country parser ────────────────────────────────────────────────────────────
const ALIAS_MAP = {
  "united states":"US","united kingdom":"GB","great britain":"GB",
  "north america":"US,CA","americas":"US,CA",
  "european":"DE,FR,GB","europe":"DE,FR,GB",
  "australia":"AU","australian":"AU","canadian":"CA",
  "american":"US","british":"GB",
  "germany":"DE","german":"DE","deutschland":"DE",
  "france":"FR","french":"FR",
  "japan":"JP","japanese":"JP",
  "canada":"CA","england":"GB",
  "apac":"JP,AU","asia":"JP,AU",
  "usa":"US","oz":"AU",
  "us":"US","gb":"GB","de":"DE","fr":"FR","jp":"JP","au":"AU","ca":"CA",
  "uk":"GB","eu":"DE,FR,GB",
};
const ALL_COUNTRIES = [
  {code:"US",flag:"🇺🇸",name:"United States"},
  {code:"GB",flag:"🇬🇧",name:"United Kingdom"},
  {code:"DE",flag:"🇩🇪",name:"Germany"},
  {code:"FR",flag:"🇫🇷",name:"France"},
  {code:"JP",flag:"🇯🇵",name:"Japan"},
  {code:"AU",flag:"🇦🇺",name:"Australia"},
  {code:"CA",flag:"🇨🇦",name:"Canada"},
];
const SORTED_ALIASES = Object.keys(ALIAS_MAP).sort((a,b) => b.length - a.length);
const SHORT_CODES    = new Set(["us","gb","de","fr","jp","au","ca","uk","eu"]);

function parseCountries(msg) {
  const text  = msg.toLowerCase();
  const found = new Set();
  for (const alias of SORTED_ALIASES) {
    const matched = SHORT_CODES.has(alias)
      ? new RegExp("\\b" + alias + "\\b").test(text)
      : text.includes(alias);
    if (matched) ALIAS_MAP[alias].split(",").forEach(c => found.add(c.trim()));
  }
  return found.size ? ALL_COUNTRIES.filter(c => found.has(c.code)) : ALL_COUNTRIES;
}

// ── Tool guess (for feed mode) ────────────────────────────────────────────────
function guessToolFromMessage(text) {
  const lower = text.toLowerCase();
  const geoKw = ["germany","german","france","french","japan","japanese","britain",
                 "australia","canada","usa","america","europe","asia","geo","check from",
                 "check for","available in","works in"];
  const bothKw = ["safe to launch","scan everything","full scan","pre-launch"];
  if (bothKw.some(k => lower.includes(k))) return "both";
  if (geoKw.some(k => lower.includes(k))) return "geocheck";
  return "ghostscan";
}

// ── Page data collection ──────────────────────────────────────────────────────
async function collectPageData() {
  let tab;
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return null;
  } catch (_) { return null; }

  const skipPatterns = ["chrome://","chrome-extension://","about:","edge://","moz-extension://"];
  if (!tab.url || skipPatterns.some(p => tab.url.startsWith(p))) {
    return { url: currentUrl, collected_url: tab.url || currentUrl,
             inline_scripts:[], window_keys:[], local_storage:{},
             session_storage:{}, meta_content:[], network_headers:[], network_urls:[],
             cookies:"", _csp_blocked: true };
  }

  const tryMsg = () => new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), 7000);
    chrome.tabs.sendMessage(tab.id, { type: "COLLECT_PAGE_DATA" }, result => {
      clearTimeout(t);
      chrome.runtime.lastError
        ? reject(new Error(chrome.runtime.lastError.message))
        : resolve(result);
    });
  });

  let domData = null;
  try {
    domData = await tryMsg();
  } catch (_) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
      await new Promise(r => setTimeout(r, 400));
      domData = await tryMsg();
    } catch (e2) {
      console.warn("POST-deploy: injection failed —", e2.message);
    }
  }

  const fetchNetData = () => new Promise(resolve => {
    chrome.runtime.sendMessage({ type: "GET_NETWORK_DATA", tabId: tab.id }, d => {
      resolve(d || { network_headers: [], network_urls: [] });
    });
  });

  let netData = await fetchNetData();
  if (!netData.network_urls?.length && !netData.network_headers?.length) {
    await new Promise(r => setTimeout(r, 500));
    netData = await fetchNetData();
  }

  console.log(`POST-deploy netData: ${netData.network_urls?.length || 0} URLs, ${netData.network_headers?.length || 0} headers`);

  if (!domData) {
    return { url: currentUrl, collected_url: currentUrl,
             inline_scripts:[], window_keys:[], local_storage:{},
             session_storage:{}, meta_content:[],
             network_headers: netData.network_headers || [],
             network_urls:    netData.network_urls    || [],
             cookies:"", _csp_blocked: true };
  }

  return {
    url:             currentUrl,
    collected_url:   domData.collected_url || currentUrl,
    inline_scripts:  domData.inline_scripts  || [],
    window_keys:     domData.window_keys      || [],
    local_storage:   domData.local_storage    || {},
    session_storage: domData.session_storage  || {},
    meta_content:    domData.meta_content     || [],
    network_headers: netData.network_headers  || [],
    network_urls:    netData.network_urls      || [],
    cookies:         domData.cookies          || "",
  };
}

// ── Main send ─────────────────────────────────────────────────────────────────
async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || isLoading) return;

  isLoading = true;
  sendBtn.disabled = true;
  suggestionsEl.style.display = "none";
  inputEl.value = "";
  inputEl.style.height = "auto";

  appendBubble("user", text);

  let latestScan = sessionLatestScan;
  if (!latestScan) {
    try {
      if (currentUrl) {
        const domain = new URL(currentUrl).hostname;
        latestScan   = await loadLatestScan(domain);
      }
    } catch (_) {}
  }

  const looksLikeScan = /key|secret|token|leak|api|scan|geo|check|country|germany|japan|france|launch|deploy|stripe|aws|github|europe|asia|safe|site|page|this/i.test(text);
  let pageData = null;
  if (looksLikeScan) {
    pageData = await collectPageData();
    if (pageData?._csp_blocked) {
      const warn = document.createElement("div");
      warn.style.cssText = "font-size:10px;color:#555;text-align:center;padding:2px 0;";
      warn.textContent = "⚠️ CSP blocked deep scan — surface scan only";
      messagesEl.appendChild(warn);
    }
  }

  const targetedCountries = parseCountries(text);

  // Choose feed mode based on guessed tool
  const toolHint = guessToolFromMessage(text);
  const feedMode = toolHint === "geocheck" ? "geo"
               : toolHint === "both"    ? "both"
               :                          "ghost";
  const feed = createProgressFeed(feedMode);

  let geoGrid = null;

  try {
    const response = await fetch(`${BACKEND_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message:      text,
        current_url:  currentUrl,
        chat_history: chatHistory.slice(-8),
        page_data:    pageData,
        latest_scan:  latestScan,
      }),
    });

    if (!response.ok) throw new Error(`Backend HTTP ${response.status}`);

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = "";
    let   toolUsed   = null;
    let   finalData  = null;

    async function processBuffer() {
      const blocks = buffer.split(/\n\n+/);
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        for (const line of block.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          let event;
          try { event = JSON.parse(raw); } catch (_) { continue; }

          switch (event.type) {
            case "progress":
              // Geo feed: only show geo_result steps, skip verbose routing steps
              if (feedMode === "geo") {
                const detail = event.detail || "";
                // Update sub-label for meaningful geo steps only
                if (detail.includes("Launched") || detail.includes("Spinning") ||
                    detail.includes("done") || detail.includes("passing")) {
                  await feed.addLine(detail);
                }
              } else {
                await feed.addLine(event.detail || event.step);
              }
              break;
            case "geo_result": {
              const r = event.data;
              if (!geoGrid) {
                geoGrid = createGeoGrid(targetedCountries);
                feed.el.appendChild(geoGrid.el);
              }
              geoGrid.update(r);
              await new Promise(r2 => requestAnimationFrame(r2));
              break;
            }
            case "complete":
              toolUsed  = event.tool_used;
              finalData = event;
              break;
          }
        }
      }
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      await processBuffer();
    }
    buffer += "\n\n";
    await processBuffer();

    if (["off_topic","chat"].includes(toolUsed)) {
      feed.remove();
    } else {
      feed.markDone();
    }

    if (!finalData) throw new Error("No complete event received.");

    const rawData    = finalData.raw_data || {};
    const isRealScan = !["off_topic","chat"].includes(toolUsed);
    const hasGhost   = isRealScan && ["ghostscan","both"].includes(toolUsed);

    if (isRealScan && currentUrl && Object.keys(rawData).length) {
      try {
        const domain = new URL(currentUrl).hostname;
        const saved  = await saveScanResult(domain, rawData);
        sessionLatestScan = saved;
      } catch (_) {}
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble assistant";

    if (isRealScan) {
      const badge = document.createElement("div");
      badge.className = `tool-badge ${toolUsed}`;
      badge.textContent = {
        ghostscan: "🔒 GHOSTSCAN",
        geocheck:  "🌍 GEOCHECK",
        both:      "🔒🌍 FULL SCAN",
      }[toolUsed] || toolUsed;
      bubble.appendChild(badge);
    }

    const txtEl = document.createElement("div");
    txtEl.innerHTML = md(finalData.response || "Done.");
    bubble.appendChild(txtEl);

    if (hasGhost) {
      const gsFindings = rawData.ghostscan?.findings;
      if (gsFindings?.length) {
        const fl = renderFindings(gsFindings);
        if (fl) bubble.appendChild(fl);
      }
      if (latestScan) {
        const diff = diffGhostFindings(latestScan, rawData);
        if (diff) {
          const diffEl = renderDiff(diff);
          if (diffEl) bubble.appendChild(diffEl);
        }
      }
    }

    messagesEl.appendChild(bubble);
    scrollBottom();

    chatHistory.push({ role: "assistant", content: finalData.response || "" });
    if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);
    chrome.storage.local.set({ chatHistory });

  } catch (err) {
    feed.remove();
    appendBubble("error", `⚠️ ${err.message}`);
  } finally {
    isLoading    = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// ── Events ────────────────────────────────────────────────────────────────────
sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 90) + "px";
});

clearBtn.addEventListener("click", async () => {
  chatHistory       = [];
  sessionLatestScan = null;
  await clearAllStorage();
  messagesEl.innerHTML = "";
  suggestionsEl.style.display = "flex";
  appendBubble("assistant", "🗑️ Cleared — chat history and all scan results wiped.");
});

document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    inputEl.value = chip.dataset.q;
    suggestionsEl.style.display = "none";
    sendMessage();
  });
});

init();