import json
import logging
import os
import time as _time

from groq import AsyncGroq

logger = logging.getLogger("deploylens.groq_client")
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

PRIMARY_MODEL  = "llama-3.1-8b-instant"
FALLBACK_MODEL = "llama-3.3-70b-versatile"

GHOSTSCAN_SYSTEM = """You are DeployLens, a security scanner in a Chrome extension popup.
Keep ALL responses to 3 lines max. The UI is very small.
Use: 🔴 CRITICAL  🟠 HIGH  🟡 WARNING  🟢 INFO
Lead with the worst issue. One short actionable fix at the end.
STRICT RULE: Never invent findings. Only report what is in the data."""

GEOCHECK_SYSTEM = """You are DeployLens, a geo-testing tool in a Chrome extension popup.
Keep responses to 3-4 lines max. Use country flag emojis. Lead with failures.
For EU countries: if GDPR/cookie banner blocks content, name what it blocks and give one fix.
If content differs between countries or geo-redirects occurred, mention it briefly.
IMPORTANT: If most/all countries failed AND issues mention "timed out" or "ERR_TIMED_OUT" or
"bot" or "access denied", note that the site likely has bot protection."""


async def _call(messages: list, max_tokens: int = 200) -> str | None:
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.15,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Groq call failed model=%s error=%s", model, e)
    return None


def _coverage_summary(coverage: dict) -> str:
    """
    Returns a short human-readable string of what was scanned.
    Used so the user knows exactly what the scan covered.
    """
    counts = coverage.get("counts", {})
    parts  = []

    scripts = counts.get("inline_scripts", 0)
    if scripts:
        parts.append(f"{scripts} script{'s' if scripts != 1 else ''}")

    keys = counts.get("window_keys", 0)
    if keys:
        parts.append(f"{keys} window var{'s' if keys != 1 else ''}")

    headers = counts.get("network_headers", 0)
    urls    = counts.get("network_urls", 0)
    if headers or urls:
        net_parts = []
        if urls:    net_parts.append(f"{urls} URL{'s' if urls != 1 else ''}")
        if headers: net_parts.append(f"{headers} header{'s' if headers != 1 else ''}")
        parts.append(f"network ({', '.join(net_parts)})")

    ls = counts.get("local_storage", 0)
    ss = counts.get("session_storage", 0)
    if ls or ss:
        parts.append(f"storage ({ls + ss} key{'s' if ls + ss != 1 else ''})")

    cookies = counts.get("cookies", 0)
    if cookies:
        parts.append("cookies")

    if not parts:
        return "nothing"

    return ", ".join(parts)


async def summarize_ghostscan(findings_data: dict, focus: str = None) -> str:
    total    = findings_data.get("total", 0)
    critical = findings_data.get("critical_count", 0)
    warning  = findings_data.get("warning", "")
    coverage = findings_data.get("scan_coverage", {})
    level    = coverage.get("level", "empty")

    logger.info("Summarizing GhostScan (total=%d coverage=%s)", total, level)

    # Stale data — skip LLM
    if warning:
        return f"⚠️ {warning}"

    # Findings found — use LLM for a good summary
    if total > 0:
        focus_note = f" Focus on: {focus}." if focus else ""
        prompt = f"Findings:{focus_note}\n{json.dumps(findings_data, indent=2)}"
        result = await _call([
            {"role": "system", "content": GHOSTSCAN_SYSTEM},
            {"role": "user",   "content": prompt},
        ])
        if result:
            return result
        parts = []
        if critical: parts.append(f"{critical} critical")
        high = findings_data.get("high_count", 0)
        if high: parts.append(f"{high} high")
        return f"🔴 Found {total} issue(s): {', '.join(parts)}. See findings below."

    # Zero findings — be honest about coverage
    scanned = _coverage_summary(coverage)

    if level == "empty":
        return (
            "⚠️ **Scan coverage: none** — no page data was received.\n"
            "The content script may not have loaded. **Reload the tab** and scan again."
        )

    if level == "low":
        return (
            f"⚠️ **Partial scan** — only {scanned} checked. "
            "Network requests not captured yet (page may need a moment to load fully). "
            "**Reload the tab** and scan again for complete results."
        )

    if level == "medium":
        return (
            f"✅ No secrets found in {scanned}.\n"
            "⚠️ **Network requests not captured** — API keys sent in URLs or headers may be missed. "
            "If the page makes API calls, scroll around to trigger them, then scan again."
        )

    # level == "high" — good coverage
    return f"✅ No secrets found. Scanned: {scanned}."


async def summarize_geocheck(geo_data: dict, focus: str = None) -> str:
    passing = geo_data.get("passing", 0)
    total   = geo_data.get("total", 0)

    logger.info("Summarizing GeoCheck (%d/%d passing)", passing, total)

    focus_note = f" Focus on: {focus}." if focus else ""
    prompt     = f"Results:{focus_note}\n{json.dumps(geo_data, indent=2)}"

    result = await _call([
        {"role": "system", "content": GEOCHECK_SYSTEM},
        {"role": "user",   "content": prompt},
    ])

    if result:
        return result
    if passing == total:
        return f"✅ All {total} countr{'y' if total == 1 else 'ies'} passed."
    return f"🌍 {passing}/{total} passing. Check grid for details."


async def generate_fix_recommendations(findings: list, page_context: dict) -> list[dict]:
    if not findings:
        return []

    framework = page_context.get("framework", "unknown")
    platform  = page_context.get("platform", "unknown")
    logger.info("Generating fix recs for %d findings (framework=%s platform=%s)",
                len(findings), framework, platform)

    summary = [
        {"type": f["type"], "severity": f["severity"], "location": f["location"]}
        for f in findings
    ]

    prompt = f"""Framework: {framework}
Platform: {platform}
Findings: {json.dumps(summary)}

Return a JSON array. Each item: {{"type": "<exact type>", "fix": "<one sentence, max 12 words, verb first, specific to {framework}>"}}
ONLY the JSON array. No markdown."""

    result = await _call([
        {"role": "system", "content": "Return ONLY a valid JSON array. No markdown, no extra text."},
        {"role": "user",   "content": prompt},
    ], max_tokens=400)

    if result:
        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                parts = cleaned.split("```")
                cleaned = parts[1] if len(parts) > 1 else cleaned
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            recs = json.loads(cleaned.strip())
            if isinstance(recs, list):
                return recs
        except Exception as e:
            logger.warning("Failed to parse fix recs: %s", e)

    return [{"type": f["type"], "fix": f.get("recommendation", "Move to server-side env var.")}
            for f in findings]


# ── Memory ─────────────────────────────────────────────────────────────────────

MEMORY_SYSTEM = """You are DeployLens, a security assistant in a Chrome extension popup.
Answer questions about scan results concisely — 2-3 sentences max.
Reference actual findings from the data. Never invent findings.
If no scan data is available, say so and suggest running a scan."""


def _format_last_scan(latest_scan: dict | None) -> str:
    if not latest_scan:
        return "NO SCAN DATA: No scan has been run yet."

    lines = []
    ts = latest_scan.get("ts")
    if ts:
        age_secs = _time.time() - (ts / 1000)
        if age_secs < 120:      age = "just now"
        elif age_secs < 3600:   age = f"{int(age_secs/60)} min ago"
        elif age_secs < 86400:  age = f"{int(age_secs/3600)} hr ago"
        else:                   age = f"{int(age_secs/86400)} day(s) ago"
        lines.append(f"Last scan: {age}")

    gs = latest_scan.get("ghostscan") or {}
    if gs and not gs.get("error"):
        total    = gs.get("total", 0)
        critical = gs.get("critical_count", 0)
        high     = gs.get("high_count", 0)
        coverage = gs.get("scan_coverage", {})
        level    = coverage.get("level", "unknown")
        lines.append(f"GhostScan: {total} finding(s) — {critical} critical, {high} high (coverage: {level})")
        for f in (gs.get("findings") or []):
            lines.append(f"  [{f['severity']}] {f['type']} at {f['location']}")
        if total == 0:
            lines.append("  No secrets detected")
    elif gs.get("error"):
        lines.append("GhostScan: unavailable (content script blocked)")
    else:
        lines.append("GhostScan: not run")

    geo = latest_scan.get("geocheck") or {}
    if geo and not geo.get("error"):
        passing = geo.get("passing", 0)
        total_c = geo.get("total", 0)
        lines.append(f"GeoCheck: {passing}/{total_c} countries passing")
        for r in (geo.get("results") or []):
            issues_str = "; ".join(r.get("issues") or [])
            cb = " (cookie banner blocks content)" if r.get("cookie_banner_blocking") else ""
            lines.append(
                f"  {r.get('flag','')} {r.get('country','')}: {r.get('status','')}{cb}"
                + (f" — {issues_str}" if issues_str else "")
            )
    else:
        lines.append("GeoCheck: not run")

    return "\n".join(lines)


async def answer_with_memory(
    message: str,
    chat_history: list,
    latest_scan: dict | None,
    current_url: str,
) -> str:
    scan_context = _format_last_scan(latest_scan)
    logger.info("Memory answer | has_scan=%s | message=%r", latest_scan is not None, message)

    system = (
        f"{MEMORY_SYSTEM}\n\n"
        f"Current URL: {current_url or 'unknown'}\n\n"
        f"SCAN DATA:\n{scan_context}"
    )

    messages = [{"role": "system", "content": system}]
    for turn in (chat_history or [])[-8:]:
        role    = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    result = await _call(messages, max_tokens=200)
    return result or "No scan data found. Try: **any api keys exposed?** or **safe to launch?**"