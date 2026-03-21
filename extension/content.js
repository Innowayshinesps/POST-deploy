(function () {
  "use strict";

  // Clear the injection guard whenever the page URL changes (SPA navigation).
  // Without this, navigating to a different site in the same tab keeps the old
  // guard set, causing the content script to silently return stale data.
  const _currentHref = location.href;
  if (window.__deployLensInjected && window.__deployLensHref !== _currentHref) {
    // URL changed — reset so we re-collect fresh data
    window.__deployLensInjected = false;
  }
  if (window.__deployLensInjected) return;
  window.__deployLensInjected = true;
  window.__deployLensHref = _currentHref;

  function safeStr(val, max) {
    try {
      const s = (typeof val === "string") ? val : JSON.stringify(val);
      return s ? s.substring(0, max || 2000) : "";
    } catch (_) { return ""; }
  }

  // Fetch same-origin JS bundles (Vercel/Next.js bundles secrets in _next/static chunks)
  async function fetchBundle(src) {
    try {
      const url = new URL(src, location.href);
      if (url.origin !== location.origin) return null;
      const resp = await fetch(url.href, { cache: "force-cache" });
      if (!resp.ok) return null;
      const text = await resp.text();
      return text.substring(0, 60000);
    } catch (_) { return null; }
  }

  async function collect() {
    const pageUrl = location.href; // capture current URL at collection time

    const data = {
      collected_url:   pageUrl,    // sent back so backend can verify it matches the tab
      inline_scripts:  [],
      window_keys:     [],
      local_storage:   {},
      session_storage: {},
      meta_content:    [],
      cookies:         "",
    };

    // ── Inline <script> tags ─────────────────────────────────────────────────
    try {
      document.querySelectorAll("script:not([src])").forEach(el => {
        const c = (el.textContent || "").trim();
        if (c.length > 10) data.inline_scripts.push(c.substring(0, 10000));
      });
    } catch (_) {}

    // ── Same-origin external bundles ─────────────────────────────────────────
    try {
      const srcs = Array.from(document.querySelectorAll("script[src]"))
        .map(el => el.getAttribute("src"))
        .filter(s => {
          if (!s) return false;
          // Skip obvious third-party analytics / tag managers
          return !/googletagmanager|gtag|analytics|hotjar|intercom|crisp|zendesk|typekit|sentry|datadog/i.test(s);
        })
        .slice(0, 12);

      const texts = await Promise.all(srcs.map(fetchBundle));
      texts.forEach((text, i) => {
        if (text) data.inline_scripts.push(`/* bundle:${srcs[i]} */\n${text}`);
      });
    } catch (_) {}

    // ── window globals ────────────────────────────────────────────────────────
    const SUSPECT = ["key","token","secret","api","auth","pass","credential",
                     "NEXT_PUBLIC","VITE_","REACT_APP_","env","config","private"];
    try {
      Object.keys(window).forEach(wk => {
        const lk = wk.toLowerCase();
        if (!SUSPECT.some(kw => lk.includes(kw.toLowerCase()))) return;
        try {
          const val = window[wk];
          if (typeof val === "string" && val.length > 4)
            data.window_keys.push(`${wk}=${val.substring(0, 300)}`);
          else if (val && typeof val === "object")
            data.window_keys.push(`${wk}=${safeStr(val, 600)}`);
        } catch (_) {}
      });
      ["__NEXT_DATA__","__nuxt","__ENV__","__APP_CONFIG__","_env_","ENV",
       "RUNTIME_CONFIG","__remixContext","__INITIAL_STATE__","__REDUX_STATE__","__APP_ENV__"]
        .forEach(gk => {
          try {
            if (window[gk] !== undefined)
              data.window_keys.push(`${gk}=${safeStr(window[gk], 4000)}`);
          } catch (_) {}
        });
    } catch (_) {}

    // ── localStorage ─────────────────────────────────────────────────────────
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k) data.local_storage[k] = (localStorage.getItem(k) || "").substring(0, 500);
      }
    } catch (_) {}

    // ── sessionStorage ────────────────────────────────────────────────────────
    try {
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i);
        if (k) data.session_storage[k] = (sessionStorage.getItem(k) || "").substring(0, 500);
      }
    } catch (_) {}

    // ── <meta> content ────────────────────────────────────────────────────────
    try {
      document.querySelectorAll("meta[content]").forEach(el => {
        const c = el.getAttribute("content") || "";
        if (c) data.meta_content.push(c.substring(0, 300));
      });
    } catch (_) {}

    // ── cookies ───────────────────────────────────────────────────────────────
    try { data.cookies = document.cookie.substring(0, 2000); } catch (_) {}

    return data;
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type !== "COLLECT_PAGE_DATA") return;

    const run = async () => {
      // Wait for full load (handles SPA navigations)
      if (document.readyState !== "complete") {
        await new Promise(resolve => {
          const check = () => document.readyState === "complete" ? resolve() : setTimeout(check, 100);
          setTimeout(check, 100);
          setTimeout(resolve, 4000); // hard deadline
        });
      }
      try {
        sendResponse(await collect());
      } catch (e) {
        sendResponse({
          collected_url: location.href,
          inline_scripts: [], window_keys: [], local_storage: {},
          session_storage: {}, meta_content: [], cookies: "", error: e.message,
        });
      }
    };

    run();
    return true;
  });
})();