"use strict";

/**
 * background.js — MV3 Service Worker
 *
 * Problem with plain in-memory netStore:
 * MV3 service workers go idle after ~30s and lose all in-memory state.
 * When the popup reopens and asks GET_NETWORK_DATA, the worker has restarted
 * with an empty netStore, so network URLs captured earlier are gone.
 *
 * Fix: use chrome.storage.session (persists for the browser session,
 * survives service worker sleep/wake cycles, cleared on browser restart).
 * Falls back to in-memory if storage.session is unavailable.
 */

const MAX_REQUESTS_PER_TAB = 300;

const SENSITIVE_HEADERS = new Set([
  "authorization",
  "x-api-key",
  "x-auth-token",
  "api-key",
  "apikey",
  "x-access-token",
  "x-secret-key",
  "x-stripe-key",
]);

// In-memory fallback (used if storage.session write fails)
const memStore = {};

// ── Storage helpers ───────────────────────────────────────────────────────────

function tabKey(tabId) {
  return `net_${tabId}`;
}

async function getTabData(tabId) {
  const key = tabKey(tabId);
  try {
    const result = await chrome.storage.session.get([key]);
    return result[key] || { network_headers: [], network_urls: [] };
  } catch (_) {
    return memStore[tabId] || { network_headers: [], network_urls: [] };
  }
}

async function setTabData(tabId, data) {
  const key = tabKey(tabId);
  try {
    await chrome.storage.session.set({ [key]: data });
  } catch (_) {
    memStore[tabId] = data;
  }
}

async function removeTabData(tabId) {
  const key = tabKey(tabId);
  try {
    await chrome.storage.session.remove([key]);
  } catch (_) {
    delete memStore[tabId];
  }
}

// ── Network interception ──────────────────────────────────────────────────────

chrome.webRequest.onBeforeSendHeaders.addListener(
  async (details) => {
    const { tabId, requestHeaders, url } = details;
    if (tabId < 0) return;

    const store = await getTabData(tabId);

    // Capture sensitive request headers
    for (const header of (requestHeaders || [])) {
      const nameLower = header.name.toLowerCase();
      if (SENSITIVE_HEADERS.has(nameLower)) {
        if (store.network_headers.length < MAX_REQUESTS_PER_TAB) {
          store.network_headers.push({
            name:  header.name,
            value: (header.value || "").substring(0, 300),
          });
        }
      }
    }

    // Capture URLs that look like API calls with keys in query params
    if (url && store.network_urls.length < MAX_REQUESTS_PER_TAB) {
      if (/[?&](key|token|secret|auth|api_?key)=/i.test(url) ||
          /api\./i.test(url) ||
          /googleapis\.com/i.test(url) ||
          /openai\.com/i.test(url) ||
          /stripe\.com/i.test(url) ||
          /sendgrid/i.test(url) ||
          /twilio/i.test(url) ||
          /firebase/i.test(url)) {
        store.network_urls.push(url.substring(0, 600));
      }
    }

    await setTabData(tabId, store);
  },
  { urls: ["<all_urls>"] },
  ["requestHeaders", "extraHeaders"]
);

// ── Clear on navigation ───────────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    removeTabData(tabId);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  removeTabData(tabId);
});

// ── Message handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_NETWORK_DATA") {
    getTabData(msg.tabId).then(data => sendResponse(data));
    return true; // async
  }

  if (msg.type === "CLEAR_NETWORK_DATA") {
    removeTabData(msg.tabId).then(() => sendResponse({ cleared: true }));
    return true;
  }
});