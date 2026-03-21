<!-- PROJECT LOGO -->
<p align="center">
  <a href="https://github.com/your-org/post-deploy">
    <img src="https://github.com/user-attachments/assets/6c97b738-193f-4d45-8688-068a20edbea5" alt="POST-deploy" width="100%" />
  </a>

  <h3 align="center">POST-deploy</h3>

  <p align="center">
    The agentic browser infrastructure for post-deployment security and geo-intelligence.
    <br />
    <br />
    <a href="https://github.com/Innowayshinesps/POST-deploy/issues">Issues</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Manifest-V3-3b82f6?style=flat" alt="MV3" />
  <img src="https://img.shields.io/badge/Python-3.11+-3b82f6?style=flat&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Powered%20by-TinyFish%20Browser%20Agents-1a3a6e?style=flat" alt="TinyFish" />
  <img src="https://img.shields.io/badge/LLM-Groq%20llama--3.1-f97316?style=flat" alt="Groq" />
  <img src="https://img.shields.io/badge/license-MIT-22c55e?style=flat" alt="License" />
  <img src="https://img.shields.io/badge/Countries-7%20proxy%20locations-a78bfa?style=flat" alt="Countries" />
  <img src="https://img.shields.io/badge/Patterns-36%20secret%20detectors-ef4444?style=flat" alt="Patterns" />
</p>

---

## About the Project

<img src="https://github.com/user-attachments/assets/dbebc057-2000-41fc-a921-952564ca338d" width="100%" alt="POST-deploy in action" />

# Agentic browser infrastructure for post-deployment confidence

POST-deploy is the **only developer tool that combines AI-driven secret scanning with real browser agents running concurrently across 7 countries** — all from a Chrome extension popup, in natural language.

You shipped. Now what? You check logs, ping teammates, cross your fingers. That's the gap POST-deploy was built to close.

Most security and geo-testing tools are either developer-time (linters, CI scanners) or infrastructure-level (WAFs, CDNs). Nothing sits at the exact moment a developer needs it most: **right after deployment, on the live URL, as real users see it**.

POST-deploy changes that. Ask it anything in plain English — _"any API keys exposed?"_, _"check if my site works in Germany"_, _"safe to launch?"_ — and it dispatches the right combination of DOM scanner and stealth browser agents to give you a real answer in under 90 seconds.

---

## What makes this different

| Capability | POST-deploy | Snyk / GitGuardian | GeoEdge / Distil |
|---|---|---|---|
| Scans the **live runtime DOM** after JS execution | ✅ | ❌ Static analysis only | ❌ |
| Detects secrets in **network request headers & URLs** | ✅ | ❌ | ❌ |
| Spins up **real stealth browsers** in 7 countries | ✅ | ❌ | ✅ Partial |
| **Concurrent** country checks (not sequential) | ✅ | ❌ | ❌ |
| **Natural language** interface — no config files | ✅ | ❌ | ❌ |
| **GDPR / cookie compliance** detection per country | ✅ | ❌ | Partial |
| Works as a **Chrome Extension** — zero infrastructure | ✅ | ❌ | ❌ |
| Cross-site contamination prevention | ✅ | N/A | N/A |
| Framework-aware fix recommendations | ✅ (Next.js, Vite, Vercel…) | Partial | ❌ |

---

## The Architecture

POST-deploy is built on three layers working in concert:

### 🔍 Layer 1 — GhostScan (DOM Intelligence)

The Chrome extension injects a content script **at `document_idle`** — after full JavaScript execution — not on static HTML. This means it catches secrets that only appear at runtime:

- **Inline scripts** including compiled Next.js / Vite / React bundles
- **Same-origin JS bundles** fetched and scanned (up to 12 bundles, 60KB each)
- **`window` globals** — framework env leaks (`__NEXT_DATA__`, `__nuxt`, `RUNTIME_CONFIG`)
- **`localStorage` / `sessionStorage`** — all keys and values
- **Network request headers** — `Authorization`, `X-API-Key`, `X-Auth-Token` and more (via `chrome.webRequest`)
- **Network URLs** — query parameters containing keys, tokens, secrets
- **`document.cookie`** and `<meta>` tag content

All intercepted network data is persisted to **`chrome.storage.session`** — surviving MV3 service worker sleep/wake cycles that would normally lose in-memory state.

**36 regex patterns** cover every major secret type:

| Provider | Pattern | Severity |
|---|---|---|
| OpenAI | `sk-[a-zA-Z0-9]{48}` | 🔴 CRITICAL |
| Anthropic | `sk-ant-[a-zA-Z0-9\-]{90,}` | 🔴 CRITICAL |
| AWS Access Key | `AKIA[0-9A-Z]{16}` | 🔴 CRITICAL |
| Stripe Secret | `sk_live_[a-zA-Z0-9]{24,}` | 🔴 CRITICAL |
| GitHub PAT | `ghp_[a-zA-Z0-9]{36}` | 🔴 CRITICAL |
| Groq | `gsk_[a-zA-Z0-9]{52}` | 🔴 CRITICAL |
| Razorpay | `rzp_live_[a-zA-Z0-9]{20,}` | 🔴 CRITICAL |
| Google API | `AIza[0-9A-Za-z\-_]{35}` | 🟠 HIGH |
| Slack Webhook | `hooks.slack.com/services/...` | 🟠 HIGH |
| Database URL | `postgres://user:pass@host` | 🔴 CRITICAL |
| JWT Secret | `jwt.?secret.*['"][^'"]{20,}` | 🔴 CRITICAL |
| Private Key | `-----BEGIN PRIVATE KEY-----` | 🔴 CRITICAL |
| + 24 more | Bearer tokens, env prefixes, passwords… | 🟡–🟠 |

**Cross-site contamination prevention:** The content script stores the URL at collection time (`collected_url`). The backend validates origin match before scanning — if you navigate to a different site between scans, stale data is discarded rather than producing false results.

**Value-level deduplication:** When two patterns (e.g. `Google API Key` and `Firebase API Key`) match the same `AIza...` string, only the more severe finding is kept. One secret = one card.

---

### 🌍 Layer 2 — GeoCheck (Stealth Browser Agents)

<img src="https://github.com/user-attachments/assets/d5d8b4a3-5bd8-41df-aeab-e807e359de4b" width="100%" alt="GeoCheck geo grid" />

GeoCheck spins up **real stealth browsers** via the TinyFish Web Agent API — not synthetic pings, not DNS lookups, not curl requests. Actual browser instances that render JavaScript, wait for dynamic content, handle redirects, and detect visual overlays.

All 7 country checks fire **simultaneously** via `asyncio.gather()`. Per TinyFish's concurrency model, requests exceeding the plan limit are auto-queued — no 429 errors, and total time equals the **slowest single country**, not the sum of all seven.

Each country agent returns a structured assessment covering:

```json
{
  "loaded": true,
  "status_code": 200,
  "main_content_visible": true,
  "cookie_banner_present": true,
  "cookie_banner_blocking": false,
  "cookie_banner_description": "We use cookies to...",
  "page_language": "de",
  "geo_redirected": false,
  "legal_compliance_issues": [
    "Cookie banner lacks explicit opt-in for GDPR compliance"
  ],
  "load_time_ms": 1842,
  "issues": []
}
```

The TinyFish goal prompt is written to production spec per their prompting guide — numbered steps, explicit schema with sample values, edge case handlers for auth walls, geo-blocks, and bot-protection detection.

**Supported proxy locations:** 🇺🇸 US · 🇬🇧 GB · 🇩🇪 DE · 🇫🇷 FR · 🇯🇵 JP · 🇦🇺 AU · 🇨🇦 CA

---

### 🧠 Layer 3 — Natural Language Intelligence


Every message goes through a **three-layer intent pipeline**:

**1. Regex pre-check** — catches referential follow-up questions before the LLM sees them. Patterns like `how to [verb] (this|that|the X)`, `why so`, `what should I do` are classified as `chat` without an API call.

**2. Groq LLM routing** — `llama-3.1-8b-instant` classifies into 5 intents:
- `ghostscan` — security scan
- `geocheck` — new geo test (new country mentioned)
- `both` — full pre-launch sweep
- `chat` — follow-up on existing results (uses memory context)
- `off_topic` — clean rejection with redirect

**3. Keyword fallback** — when Groq is unavailable, deterministic routing keeps the extension working with no degradation.

**Country parsing** uses word-boundary regex for short ISO codes (`ca`, `de`, `fr`, `jp`) to prevent substring false matches — `"ca"` inside `"scan"` no longer fires Canada.

**Memory context** — before every follow-up question, the last scan result for the current domain is loaded from `chrome.storage.local` and injected into Groq's system prompt as structured text. The LLM has access to actual finding types, severities, geo results, and timestamps — not just conversation history.

---

## Live Demo

<img src="https://github.com/user-attachments/assets/32a7d6e0-775e-4bba-9c17-a35abd29381d" width="100%" alt="POST-deploy demo GIF — user opens extension on a Vercel site, runs scan, sees ghostscan findings and geo grid results" width="100%" alt="POST-deploy demo GIF" />

---

## Key Features

<table>
<tr>
<td width="50%">

### 🔒 GhostScan
Real-time secret detection on the live DOM. Catches what static scanners miss — secrets that only appear after JavaScript executes, in network headers, bundled JS files, and browser storage.

- 36 battle-tested patterns
- Framework detection (Next.js, Vite, React, Nuxt)
- Framework-aware fix recommendations via LLM
- Scan coverage reporting (high/medium/low/empty)
- Cross-site contamination guard
- Value-level deduplication

</td>
<td width="50%">

### 🌍 GeoCheck
Live browser agents in 7 countries running concurrently. Not synthetic — real browsers, real rendering, real JavaScript execution.

- GDPR / cookie compliance detection
- Content language verification
- Geo-redirect detection
- Cookie banner blocking analysis
- Legal compliance issue extraction
- Bot-protection detection

</td>
</tr>
<tr>
<td width="50%">

### 🧠 Conversational Interface
Natural language commands. No configuration files, no dashboards, no onboarding.

- Intent routing with 5-category classification
- Referential follow-up understanding
- Memory-aware answers from previous scans
- Off-topic guardrails with helpful redirects
- Predictive progress animation (instant feedback)

</td>
<td width="50%">

### 📊 Scan Intelligence
Results that go beyond pass/fail — context, comparison, and actionable guidance.

- Diff vs. previous scans (Fixed / New / Still present)
- Scan-to-scan baseline comparison
- Groq-generated plain-English summaries
- Inline fix recommendations per finding
- Coverage transparency (what was actually scanned)

</td>
</tr>
</table>

---

## Getting Started

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Chrome / Chromium | Any recent version |
| [Groq API Key](https://console.groq.com/keys) | Free tier sufficient |
| [TinyFish API Key](https://agent.tinyfish.ai/api-keys) | Required for GeoCheck |

### 1. Clone the repository

```sh
git clone https://github.com/Innowayshinesps/POST-deploy.git
cd post-deploy
```

### 2. Configure API keys

Open `backend/.env` and add your keys:

```env
TINYFISH_API_KEY=your_tinyfish_api_key_here
GROQ_API_KEY=your_groq_api_key_here
ALLOWED_ORIGINS=*
```

> **Note:** Set `ALLOWED_ORIGINS` to your extension ID in production:
> `chrome-extension://your_extension_id_here`

### 3. Start the backend

```sh
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Verify the backend is running:

```sh
curl http://localhost:8000/health
# → {"status":"ok","service":"POST-deploy","version":"1.1.0"}
```

### 4. Load the Chrome Extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder

<img src="https://github.com/user-attachments/assets/0757b9ae-249d-4c68-b418-c833a126f24f" width="600" alt="Chrome extension loading" />

### 5. Use it

Navigate to any deployed site. Click the **POST-deploy** icon. Type naturally:

```
any api keys exposed?
check germany
safe to launch?
how do I fix that?
```

---

## Project Structure

```
post-deploy/
├── backend/                          # FastAPI Python backend
│   ├── main.py                       # App entry, CORS, logging
│   ├── requirements.txt
│   ├── .env                          # API keys (never commit)
│   │
│   ├── routes/
│   │   ├── chat.py                   # SSE streaming — intent → tool → result
│   │   ├── ghostscan.py              # Pattern matching engine
│   │   └── geocheck.py               # Geo SSE streaming endpoint
│   │
│   ├── services/
│   │   ├── intent_router.py          # Groq LLM + regex pre-check + keyword fallback
│   │   ├── tinyfish.py               # TinyFish API wrapper (concurrent)
│   │   └── groq_client.py            # Summarization + fix recs + memory answers
│   │
│   └── utils/
│       ├── patterns.py               # 36 secret detection regex patterns
│       └── country_parser.py         # Word-boundary country name parsing
│
└── extension/                        # Chrome Extension (MV3, pure JS)
    ├── manifest.json                 # Permissions, service worker declaration
    ├── popup.html                    # Chat UI — dark premium design
    ├── popup.js                      # SSE client, predictive animation, rendering
    ├── content.js                    # DOM scanner — injected at document_idle
    ├── background.js                 # Service worker, network interception
    └── icons/
```

---

## How It Works — End to End

```
User message
    │
    ├─ Regex pre-check (0ms)          "how to fix this" → chat (no API call)
    │
    ├─ Groq intent routing (~600ms)   classifies: ghostscan | geocheck | both | chat | off_topic
    │
    ├─ GhostScan (if needed)
    │   ├─ content.js → DOM + bundles + storage + cookies
    │   ├─ background.js → network headers + URLs (chrome.storage.session)
    │   ├─ 36 patterns × all sources → deduplicated findings
    │   └─ Groq → framework-aware fix recommendations
    │
    ├─ GeoCheck (if needed)
    │   ├─ asyncio.gather() → all countries simultaneously
    │   ├─ TinyFish stealth browsers → real rendering
    │   ├─ SSE stream → results arrive as each country completes
    │   └─ Groq → geo + compliance summary
    │
    └─ complete event → popup renders result bubble
```

---

## API Reference

The backend exposes three streaming endpoints:

### `POST /chat`

The main entry point. SSE stream returning progress events, then a single `complete` event.

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "any api keys exposed?",
    "current_url": "https://yoursite.com",
    "page_data": { ... },
    "latest_scan": null
  }'
```

**SSE event types:**

| Type | Payload | When |
|---|---|---|
| `progress` | `{step, detail}` | During processing |
| `geo_result` | `{country, status, issues, ...}` | As each country completes |
| `complete` | `{response, tool_used, raw_data}` | When everything is done |

### `POST /ghostscan`

Direct pattern scan endpoint. Accepts page data, returns structured findings.

### `POST /geocheck`

SSE streaming geo check. Returns one `data:` event per country, then a `complete` summary.

---

## Technical Deep Dive

### Why SSE instead of WebSockets?

GeoCheck takes 30–90 seconds. Users need to see countries completing in real time rather than staring at a spinner. Server-Sent Events are unidirectional and stateless — perfect for streaming progress from a FastAPI generator function. Each country result is yielded the moment `asyncio.gather()` completes it, with no need for bidirectional communication.

### Why `chrome.storage.session` for network data?

MV3 service workers sleep after ~30 seconds of inactivity and lose all in-memory state. A naive `netStore = {}` object in `background.js` would be empty by the time the popup reopened. `chrome.storage.session` persists for the lifetime of the browser session regardless of service worker state — network data captured 10 minutes ago is still available when the user runs a scan.

### Why a regex pre-check before the LLM?

The Groq LLM (`llama-3.1-8b-instant`) occasionally misclassifies referential follow-up questions. For example, "how to **secure** that" contains the word "secure" which the model associates with `ghostscan`. A fast regex layer checks for referential patterns (`how to [verb] (this|that|it|the X)`, `why so`, `what should I do`) before the API call — catching ~40% of follow-up questions with zero latency and zero token cost.

### Why word-boundary matching for country codes?

Short ISO codes like `ca`, `de`, `fr`, `jp`, `au` are dangerous substrings. `"ca"` appears inside `"scan"`, `"de"` inside `"deploy"`, `"fr"` inside `"framework"`. All two and three letter codes are matched with `\b` word boundaries in both Python (`re.compile`) and JavaScript (`new RegExp("\\b" + alias + "\\b")`).

### Scan Coverage Transparency

Every GhostScan result includes a `scan_coverage` object:

```json
{
  "scan_coverage": {
    "level": "medium",
    "counts": {
      "inline_scripts": 1,
      "window_keys": 0,
      "network_urls": 0,
      "network_headers": 2,
      "local_storage": 0
    }
  }
}
```

When `network_urls = 0`, the summary explicitly warns: _"⚠️ Network requests not captured — API keys sent in URLs may be missed."_ Users always know what was and wasn't scanned.

---

## Built With

<p align="center">
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-Framework-009688?style=for-the-badge&logo=fastapi&logoColor=white" /></a>
  <a href="https://console.groq.com"><img src="https://img.shields.io/badge/Groq-LLM%20Inference-f97316?style=for-the-badge" /></a>
  <a href="https://agent.tinyfish.ai"><img src="https://img.shields.io/badge/TinyFish-Browser%20Agents-3b82f6?style=for-the-badge" /></a>
  <a href="https://developer.chrome.com/docs/extensions/mv3/"><img src="https://img.shields.io/badge/Chrome%20Extension-MV3-4285F4?style=for-the-badge&logo=google-chrome&logoColor=white" /></a>
  <a href="https://docs.python.org/3.11/"><img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" /></a>
  <a href="https://github.com/sse-starlette/sse-starlette"><img src="https://img.shields.io/badge/SSE-Starlette-009688?style=for-the-badge" /></a>
  <a href="https://www.python-httpx.org/"><img src="https://img.shields.io/badge/httpx-Async%20HTTP-ff69b4?style=for-the-badge" /></a>
</p>

---

## Roadmap

The current version (v1.1) covers the core scan + geo loop. Planned for upcoming releases:

- [ ] **Advanced Workflow Automation** — Automatically test real user journeys with smart form filling, button clicks, and multi-step interactions. Execute complex workflows across live websites seamlessly using TinyFish infrastructure.
- [ ] **Policy Monitor** — Daily scraping of Stripe, OpenAI, AWS, GitHub, Vercel ToS pages. Semantic diff against previous versions using embeddings. Surface relevant policy changes inside the chat interface.
- [ ] **Scan History Dashboard** — Visual timeline of findings per domain across scans. Trend lines for critical/high counts. Export to PDF.
- [ ] **Team Sharing** — Share scan results via permalink. Slack/email digest on new critical findings.
- [ ] **CI/CD Integration** — GitHub Action that runs POST-deploy on every deployment. Block merge if CRITICAL findings detected.
- [ ] **More Proxy Locations** — India, Brazil, South Korea, UAE as TinyFish expands supported regions.
- [ ] **Chrome Web Store** — Public listing with OAuth-based cloud backend option.

---

## Security & Privacy

- **No secrets are stored on any server.** All scan results live in `chrome.storage.local` — encrypted on your device, cleared on demand.
- **Secret values are never transmitted in full.** The backend truncates all matched values to `first4...last4` before returning them.
- **Network interception is read-only.** `chrome.webRequest` observes but never blocks or modifies requests.
- **TinyFish browsers are ephemeral.** Each geo run uses a fresh browser session with no stored cookies or credentials.
- **Groq processes summaries only** — the LLM never sees raw secret values, only finding types and severity counts.

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

```sh
# Fork and clone
git clone https://github.com/Innowayshinesps/POST-deploy.git

# Create a feature branch
git checkout -b feature/your-feature-name

# Make your changes
# Run the backend
cd backend && uvicorn main:app --reload

# Load the extension from extension/ in Chrome developer mode

# Submit a PR
```

### Adding a new secret pattern

Add an entry to `backend/utils/patterns.py`:

```python
{
    "name": "My Provider API Key",
    "regex": r"myprovider_[a-zA-Z0-9]{32}",
    "severity": "CRITICAL",          # CRITICAL | HIGH | WARNING | INFO
    "is_safe_in_frontend": False,
    "recommendation": "Move to server-side environment variable.",
}
```

No other files need changes — the pattern is automatically picked up by the scan engine.

---

## Acknowledgements

Special thanks to the infrastructure that powers POST-deploy:

- [TinyFish](https://agent.tinyfish.ai) — stealth browser agent API that makes real geo testing possible
- [Groq](https://groq.com) — ultra-fast LLM inference that makes sub-second intent routing practical
- [FastAPI](https://fastapi.tiangolo.com) + [sse-starlette](https://github.com/sysid/sse-starlette) — the async SSE backbone
- [httpx](https://www.python-httpx.org) — async HTTP client for concurrent TinyFish requests

---

<p align="center">
  <strong>Built for developers who ship fast and sleep well.</strong>
  <br /><br />
  <a href="https://github.com/Innowayshinesps/POST-deploy/stargazers">⭐ Star this repo</a>
  ·
  <a href="https://github.com/Innowayshinesps/POST-deploy/issues/new">🐛 Report a bug</a>
  ·
  <a href="https://github.com/Innowayshinesps/POST-deploy/discussions/new">💡 Request a feature</a>
</p>
