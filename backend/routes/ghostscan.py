import logging
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from utils.patterns import SECRET_PATTERNS

logger = logging.getLogger("deploylens.ghostscan")
router = APIRouter()

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}


class GhostScanRequest(BaseModel):
    url:             str
    inline_scripts:  Optional[List[str]]            = []
    window_keys:     Optional[List[str]]             = []
    local_storage:   Optional[Dict[str, str]]        = {}
    session_storage: Optional[Dict[str, str]]        = {}
    meta_content:    Optional[List[str]]             = []
    network_headers: Optional[List[Dict[str, str]]]  = []
    network_urls:    Optional[List[str]]             = []
    cookies:         Optional[str]                   = ""
    collected_url:   Optional[str]                   = None


def _truncate(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _same_origin(url_a: str, url_b: str) -> bool:
    try:
        a = urlparse(url_a)
        b = urlparse(url_b)
        return a.scheme == b.scheme and a.netloc == b.netloc
    except Exception:
        return True


def _scan_text(text: str, location: str, findings_map: dict) -> None:
    for pattern in SECRET_PATTERNS:
        try:
            matches = re.findall(pattern["regex"], text, re.IGNORECASE)
        except re.error as e:
            logger.warning("Bad regex for pattern %s: %s", pattern["name"], e)
            continue

        for match in matches:
            matched_str = match if isinstance(match, str) else (match[0] if match else "")
            if not matched_str or len(matched_str) < 8:
                continue

            # Deduplicate by matched value — prevents Google API Key + Firebase API Key
            # both firing on the same AIza... string
            value_key = matched_str[:12]

            if value_key in findings_map:
                existing = findings_map[value_key]
                # Upgrade to more severe pattern if needed
                if SEVERITY_ORDER.get(pattern["severity"], 99) < SEVERITY_ORDER.get(existing["severity"], 99):
                    findings_map[value_key]["type"]               = pattern["name"]
                    findings_map[value_key]["severity"]           = pattern["severity"]
                    findings_map[value_key]["recommendation"]     = pattern.get("recommendation", "")
                    findings_map[value_key]["is_safe_in_frontend"] = pattern.get("is_safe_in_frontend", False)
                if location not in findings_map[value_key]["locations"]:
                    findings_map[value_key]["locations"].append(location)
            else:
                entry = {
                    "type":                pattern["name"],
                    "severity":            pattern["severity"],
                    "locations":           [location],
                    "value_preview":       _truncate(matched_str),
                    "is_safe_in_frontend": pattern.get("is_safe_in_frontend", False),
                    "recommendation":      pattern.get("recommendation", "Move to server-side environment variable."),
                }
                if pattern.get("note"):
                    entry["note"] = pattern["note"]
                findings_map[value_key] = entry


def _coverage_level(counts: dict) -> str:
    """
    Returns a confidence label based on how much data was scanned.
      high   — scripts + network data present
      medium — scripts only, no network data
      low    — almost nothing (1 script or less, no network)
      empty  — literally nothing was scanned
    """
    scripts = counts["inline_scripts"]
    net     = counts["network_urls"] + counts["network_headers"]
    keys    = counts["window_keys"]
    storage = counts["local_storage"] + counts["session_storage"]

    total = scripts + net + keys + storage
    if total == 0:
        return "empty"
    if scripts <= 1 and net == 0 and keys == 0 and storage == 0:
        return "low"
    if net == 0 and scripts > 0:
        return "medium"
    return "high"


async def run_ghostscan_logic(data: dict) -> dict:
    t0  = time.monotonic()
    url = data.get("url", "unknown")
    collected_url = data.get("collected_url")

    # Cross-site contamination guard
    if collected_url and not _same_origin(url, collected_url):
        elapsed = int((time.monotonic() - t0) * 1000)
        logger.warning(
            "GhostScan → STALE DATA DISCARDED  tab_url=%s  collected_url=%s",
            url, collected_url,
        )
        return {
            "findings": [], "total": 0,
            "critical_count": 0, "high_count": 0,
            "warning_count": 0, "safe_count": 0,
            "scan_duration_ms": elapsed,
            "warning": (
                "Page data was collected from a different origin than the current tab. "
                "Please reload the tab and scan again."
            ),
            "scan_coverage": {"level": "empty", "counts": {}},
        }

    # Build coverage counts
    inline_count = len(data.get("inline_scripts") or [])
    window_count = len(data.get("window_keys") or [])
    ls_count     = len(data.get("local_storage") or {})
    ss_count     = len(data.get("session_storage") or {})
    meta_count   = len(data.get("meta_content") or [])
    header_count = len(data.get("network_headers") or [])
    url_count    = len(data.get("network_urls") or [])
    has_cookies  = bool(data.get("cookies"))

    coverage_counts = {
        "inline_scripts":  inline_count,
        "window_keys":     window_count,
        "local_storage":   ls_count,
        "session_storage": ss_count,
        "network_headers": header_count,
        "network_urls":    url_count,
        "cookies":         1 if has_cookies else 0,
    }
    coverage = _coverage_level(coverage_counts)

    logger.info(
        "GhostScan → starting  url=%s  collected_url=%s  coverage=%s  "
        "inline_scripts=%d  window_keys=%d  ls=%d  ss=%d  headers=%d  urls=%d",
        url, collected_url or "not_provided", coverage,
        inline_count, window_count, ls_count, ss_count, header_count, url_count,
    )

    findings_map: dict = {}

    for i, script in enumerate(data.get("inline_scripts") or []):
        _scan_text(script, f"Inline script #{i + 1}", findings_map)

    for key_str in data.get("window_keys") or []:
        _scan_text(key_str, "window object", findings_map)

    for k, v in (data.get("local_storage") or {}).items():
        _scan_text(f"{k}={v}", f"localStorage[{k}]", findings_map)

    for k, v in (data.get("session_storage") or {}).items():
        _scan_text(f"{k}={v}", f"sessionStorage[{k}]", findings_map)

    for content in data.get("meta_content") or []:
        _scan_text(content, "meta tag", findings_map)

    for header in data.get("network_headers") or []:
        name  = header.get("name", "")
        value = header.get("value", "")
        _scan_text(f"{name}: {value}", f"Network header — {name}", findings_map)

    for url_str in data.get("network_urls") or []:
        _scan_text(url_str, f"Network URL — {url_str[:80]}", findings_map)

    if data.get("cookies"):
        _scan_text(data["cookies"], "document.cookie", findings_map)

    # Flatten and sort
    findings = []
    for f in findings_map.values():
        f["location"] = ", ".join(f.pop("locations"))
        findings.append(f)
    findings.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 99))

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1

    logger.info(
        "GhostScan → done  url=%s  total=%d  critical=%d  high=%d  warning=%d  coverage=%s  elapsed=%dms",
        url, len(findings),
        counts.get("CRITICAL", 0), counts.get("HIGH", 0),
        counts.get("WARNING", 0), coverage, elapsed_ms,
    )

    return {
        "findings":         findings,
        "total":            len(findings),
        "critical_count":   counts.get("CRITICAL", 0),
        "high_count":       counts.get("HIGH", 0),
        "warning_count":    counts.get("WARNING", 0),
        "safe_count":       counts.get("INFO", 0),
        "scan_duration_ms": elapsed_ms,
        # Coverage tells the UI how much data was actually scanned
        "scan_coverage": {
            "level":  coverage,   # "high" | "medium" | "low" | "empty"
            "counts": coverage_counts,
        },
    }


@router.post("/ghostscan")
async def ghostscan(request: GhostScanRequest):
    try:
        result = await run_ghostscan_logic(request.model_dump())
        return JSONResponse(result)
    except Exception as e:
        logger.error("GhostScan endpoint error: %s", e, exc_info=True)
        return JSONResponse(
            {"error": True, "message": str(e), "code": "GHOSTSCAN_ERROR"},
            status_code=500,
        )