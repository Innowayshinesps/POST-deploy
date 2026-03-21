"""
tinyfish.py
TinyFish Web Agent API wrapper.

GeoCheck goal is written per TinyFish prompting guide best practices:
- Explicit field definitions with sample values for schema consistency
- Step-by-step instructions
- Edge case handling
- Cookie/GDPR banner detection
- Content visibility and legal compliance checks
- Explicit fallbacks for auth walls and error states
"""

import asyncio
import json
import logging
import os
import time
from typing import Callable

import httpx

logger = logging.getLogger("deploylens.tinyfish")

TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY", "")
TINYFISH_SYNC_URL = "https://agent.tinyfish.ai/v1/automation/run"
TINYFISH_SSE_URL  = "https://agent.tinyfish.ai/v1/automation/run-sse"
TIMEOUT_SECONDS   = 120


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "X-API-Key": TINYFISH_API_KEY,
    }


# Production-quality goal written per TinyFish prompting guide.
# Explicit schema with sample values ensures consistent field names across runs.
# Numbered steps help the agent handle multi-state pages (cookie banners etc.)
GEOCHECK_GOAL = """You are testing this webpage for geo-availability and legal compliance.

Follow these steps in order:
1. Load the page and wait for main content to fully render.
2. Check for any cookie consent banner, GDPR notice, or privacy overlay.
   - If present: note whether it blocks the main content or just overlays it.
   - Do NOT dismiss it — record its presence and whether it's blocking.
3. Assess whether the main content of the page is visible and readable.
4. Check if the page is in the correct language for the country you're browsing from,
   or if it has been geo-redirected to a different version.
5. Note the page title, HTTP status, and approximate load time.
6. Identify any issues: error messages, access denied, geo-blocks, blank content,
   broken layouts, missing images, or login walls.
7. For EU countries (DE, FR, GB): specifically check if a cookie/GDPR banner is
   present AND whether it blocks CTAs, buttons, or main content.

Return ONLY a JSON object matching this exact structure (copy field names exactly):
{
  "loaded": true,
  "status_code": 200,
  "main_content_visible": true,
  "error_message": null,
  "cookie_banner_present": false,
  "cookie_banner_blocking": false,
  "cookie_banner_description": null,
  "page_language": "en",
  "geo_redirected": false,
  "geo_redirect_destination": null,
  "title": "Page Title Here",
  "load_time_ms": 1500,
  "legal_compliance_issues": [],
  "issues": []
}

Field rules:
- loaded: true if page loaded without error, false otherwise
- status_code: HTTP status if detectable, otherwise null
- main_content_visible: true if users can read/interact with the page
- error_message: null if no error, otherwise a short description
- cookie_banner_present: true if any cookie/GDPR/privacy notice is shown
- cookie_banner_blocking: true ONLY if the banner physically covers or disables main content
- cookie_banner_description: brief description of what the banner says, or null
- page_language: 2-letter ISO language code of the displayed content
- geo_redirected: true if the URL redirected to a country-specific version
- geo_redirect_destination: the final URL if redirected, otherwise null
- title: the page title as displayed in the browser tab
- load_time_ms: estimated load time in milliseconds, or null if unknown
- legal_compliance_issues: array of strings describing GDPR/legal concerns, empty array if none
- issues: array of strings describing any other problems found, empty array if none

If the page is behind a login wall, set:
  loaded=true, main_content_visible=false, issues=["Page requires authentication"]

If the page shows an access denied or geo-block:
  loaded=false, error_message="Access denied / geo-blocked", issues=["Content not available in this region"]

Return ONLY the JSON object. No markdown, no explanation, no extra text."""


def _payload(url: str, country_code: str) -> dict:
    return {
        "url":            url,
        "goal":           GEOCHECK_GOAL,
        "browser_profile": "stealth",
        "proxy_config": {
            "enabled":      True,
            "country_code": country_code,
        },
    }


def _parse_result(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned.strip())
        except Exception:
            pass
    return {}


def _error_result(country: dict, status: str, issues: list, load_time_ms=None) -> dict:
    """
    Build a consistent error/timeout result dict.
    Always sets 'country' (the ISO code string) so chat.py can safely access r['country'].
    Using {**country} alone would give 'code'/'flag'/'name' but NOT 'country'.
    """
    return {
        "country":    country["code"],   # ← this is what chat.py uses
        "flag":       country["flag"],
        "name":       country["name"],
        "status":     status,
        "issues":     issues,
        "load_time_ms": load_time_ms,
        "status_code": None,
        "title":       None,
        "page_language": None,
        "cookie_banner_present": False,
        "cookie_banner_blocking": False,
        "geo_redirected": False,
        "legal_compliance_issues": [],
    }


def _normalise(country: dict, assessment: dict, status: str) -> dict:
    """Build a consistent country result dict from TinyFish assessment."""
    issues = list(assessment.get("issues") or [])
    legal  = list(assessment.get("legal_compliance_issues") or [])

    if assessment.get("cookie_banner_blocking"):
        issues.append("Cookie consent banner is blocking main content")
    if not assessment.get("main_content_visible", True):
        issues.append("Main content not visible to users")
    if assessment.get("error_message"):
        msg = str(assessment["error_message"])
        if msg and msg.lower() not in ("null", "none", ""):
            issues.append(msg)
    if legal:
        issues.extend(legal)
    if assessment.get("geo_redirected"):
        dest = assessment.get("geo_redirect_destination", "")
        issues.append(f"Page geo-redirected to: {dest}" if dest else "Page was geo-redirected")

    # Deduplicate issues
    seen = set()
    deduped = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            deduped.append(issue)

    final_status = "pass" if assessment.get("loaded", False) and not deduped else "fail"
    if status in ("timeout", "error"):
        final_status = status

    return {
        "country":               country["code"],
        "flag":                  country["flag"],
        "name":                  country["name"],
        "status":                final_status,
        "load_time_ms":          assessment.get("load_time_ms"),
        "status_code":           assessment.get("status_code"),
        "title":                 assessment.get("title"),
        "page_language":         assessment.get("page_language"),
        "cookie_banner_present": assessment.get("cookie_banner_present", False),
        "cookie_banner_blocking": assessment.get("cookie_banner_blocking", False),
        "cookie_banner_description": assessment.get("cookie_banner_description"),
        "geo_redirected":        assessment.get("geo_redirected", False),
        "legal_compliance_issues": legal,
        "issues":                deduped,
    }


# ── Sync check ────────────────────────────────────────────────────────────────

async def _check_sync(client: httpx.AsyncClient, url: str, country: dict) -> dict:
    code = country["code"]
    t0   = time.monotonic()
    logger.info("GeoCheck → starting  country=%s  url=%s", code, url)

    try:
        resp = await client.post(
            TINYFISH_SYNC_URL,
            headers=_headers(),
            json=_payload(url, code),
            timeout=TIMEOUT_SECONDS,
        )
        elapsed = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            logger.warning("GeoCheck → HTTP %s  country=%s  elapsed=%dms", resp.status_code, code, elapsed)
            return _error_result(country, "error", [f"API returned HTTP {resp.status_code}"], elapsed)

        data       = resp.json()
        run_status = data.get("status", "FAILED")
        result_raw = data.get("result", {})

        if run_status == "FAILED" or not result_raw:
            err  = data.get("error") or {}
            msg  = err.get("message", "Automation failed") if isinstance(err, dict) else str(err)
            logger.warning("GeoCheck → FAILED  country=%s  reason=%s  elapsed=%dms", code, msg, elapsed)
            return _error_result(country, "error", [msg], elapsed)

        assessment = _parse_result(result_raw)
        result     = _normalise(country, assessment, "")
        logger.info("GeoCheck → done  country=%s  status=%s  elapsed=%dms", code, result["status"], elapsed)
        return result

    except asyncio.TimeoutError:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning("GeoCheck → TIMEOUT  country=%s  elapsed=%dms", code, elapsed)
        return _error_result(country, "timeout", [f"Timed out after {TIMEOUT_SECONDS}s"], elapsed)
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.error("GeoCheck → ERROR  country=%s  error=%s  elapsed=%dms", code, exc, elapsed)
        return _error_result(country, "error", [f"Could not reach from {country['name']}: {exc}"], elapsed)


async def run_concurrent(url: str, countries: list[dict]) -> list[dict]:
    """Fire all country checks concurrently using asyncio.gather."""
    logger.info("GeoCheck → firing %d concurrent requests  url=%s", len(countries), url)
    t0 = time.monotonic()

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS + 10) as client:
        tasks   = [_check_sync(client, url, c) for c in countries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    normalized = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            c = countries[i]
            logger.error("GeoCheck → unhandled exception  country=%s  error=%s", c["code"], r)
            normalized.append(_error_result(c, "error", [str(r)]))
        else:
            normalized.append(r)

    elapsed  = int((time.monotonic() - t0) * 1000)
    passing  = sum(1 for r in normalized if r.get("status") == "pass")
    logger.info("GeoCheck → all done  %d/%d passing  total_elapsed=%dms",
                passing, len(countries), elapsed)
    return normalized


# ── SSE check ─────────────────────────────────────────────────────────────────

async def _check_sse(url: str, country: dict, on_result: Callable) -> None:
    code = country["code"]
    t0   = time.monotonic()
    logger.info("GeoCheck SSE → starting  country=%s", code)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS + 10) as client:
            async with client.stream(
                "POST", TINYFISH_SSE_URL,
                headers=_headers(),
                json=_payload(url, code),
            ) as resp:
                if resp.status_code != 200:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    logger.warning("GeoCheck SSE → HTTP %s  country=%s", resp.status_code, code)
                    await on_result(_error_result(country, "error",
                                                  [f"API returned HTTP {resp.status_code}"], elapsed))
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type") == "COMPLETE":
                        elapsed    = int((time.monotonic() - t0) * 1000)
                        run_status = event.get("status", "FAILED")
                        result_raw = event.get("resultJson") or event.get("result") or {}

                        if run_status == "FAILED" or not result_raw:
                            # Log the full event so we can debug what TinyFish returned
                            err_info = event.get("error") or event.get("errorMessage") or "Automation failed"
                            if isinstance(err_info, dict):
                                err_msg = err_info.get("message", "Automation failed")
                            else:
                                err_msg = str(err_info)
                            logger.warning("GeoCheck SSE → FAILED  country=%s  status=%s  error=%s  event_keys=%s",
                                           code, run_status, err_msg, list(event.keys()))
                            await on_result(_error_result(country, "error",
                                                          [f"TinyFish error: {err_msg}"], elapsed))
                            return

                        assessment = _parse_result(result_raw)
                        result     = _normalise(country, assessment, "")
                        logger.info("GeoCheck SSE → done  country=%s  status=%s  elapsed=%dms",
                                    code, result["status"], elapsed)
                        await on_result(result)
                        return

    except asyncio.TimeoutError:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning("GeoCheck SSE → TIMEOUT  country=%s  elapsed=%dms", code, elapsed)
        await on_result(_error_result(country, "timeout",
                                      [f"Timed out after {TIMEOUT_SECONDS}s"], elapsed))
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.error("GeoCheck SSE → ERROR  country=%s  error=%s", code, exc)
        await on_result(_error_result(country, "error",
                                      [f"Could not reach from {country['name']}: {exc}"], elapsed))


async def run_sse_concurrent(url: str, countries: list[dict], on_result: Callable) -> None:
    """Fire all country SSE checks concurrently."""
    logger.info("GeoCheck SSE → firing %d concurrent tasks", len(countries))
    tasks = [asyncio.create_task(_check_sse(url, c, on_result)) for c in countries]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("GeoCheck SSE → all tasks finished")