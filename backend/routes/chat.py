import asyncio
import json
import logging
import time
from typing import Optional, List

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from services.intent_router import route_intent
from services.groq_client import (
    summarize_ghostscan, summarize_geocheck,
    generate_fix_recommendations, answer_with_memory,
)
from services.tinyfish import run_sse_concurrent
from routes.ghostscan import run_ghostscan_logic
from utils.country_parser import ALL_COUNTRIES, parse_countries, SUPPORTED_LIST

logger = logging.getLogger("deploylens.chat")
router = APIRouter()


def _pattern_count():
    from utils.patterns import SECRET_PATTERNS
    return len(SECRET_PATTERNS)
PATTERN_COUNT = _pattern_count()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message:      str
    current_url:  Optional[str] = ""
    chat_history: Optional[List[ChatMessage]] = []
    page_data:    Optional[dict] = None
    latest_scan:  Optional[dict] = None


def _detect_framework(page_data: dict | None) -> dict:
    if not page_data:
        return {"framework": "unknown", "platform": "unknown"}

    all_text = " ".join([
        " ".join(page_data.get("window_keys") or []),
        " ".join(page_data.get("inline_scripts") or [])[:3000],
        " ".join(page_data.get("meta_content") or []),
        page_data.get("url", ""),
    ]).lower()

    framework = "unknown"
    if "__next_data__" in all_text or "_next/static" in all_text:
        framework = "Next.js"
    elif "vite" in all_text or "__vite" in all_text:
        framework = "Vite"
    elif "__nuxt" in all_text:
        framework = "Nuxt.js"
    elif "react" in all_text:
        framework = "React"
    elif "vue" in all_text:
        framework = "Vue"

    platform = "unknown"
    url = page_data.get("url", "").lower()
    if "vercel.app" in url or "vercel" in all_text:
        platform = "Vercel"
    elif "netlify.app" in url or "netlify" in all_text:
        platform = "Netlify"
    elif "render.com" in url:
        platform = "Render"
    elif "railway.app" in url:
        platform = "Railway"

    return {"framework": framework, "platform": platform}


def _emit(type_: str, **kwargs) -> str:
    return json.dumps({"type": type_, **kwargs})


async def _stream(request: ChatRequest):
    message      = request.message
    current_url  = request.current_url or ""
    page_data    = request.page_data
    latest_scan  = request.latest_scan
    chat_history = [m.model_dump() for m in (request.chat_history or [])]
    t_total      = time.monotonic()

    # ── Intent routing ────────────────────────────────────────────────────────
    yield {"data": _emit("progress", step="routing", detail="🧠 Figuring out what you need...")}
    logger.info("Chat → routing intent  message=%r  url=%s", message, current_url)

    intent     = await route_intent(message, current_url)
    tool       = intent.get("tool", "ghostscan")
    intent_msg = intent.get("message", "")
    focus      = intent.get("focus")
    chat_reply = intent.get("chat_reply")

    logger.info("Chat → tool=%s  focus=%s", tool, focus)

    # ── Off-topic ─────────────────────────────────────────────────────────────
    if tool == "off_topic":
        reply = chat_reply or "I'm a deployment security tool. Try: **any api keys exposed?** or **check germany**."
        yield {"data": _emit("complete", response=reply, tool_used="off_topic", raw_data={})}
        return

    # ── Chat / memory ─────────────────────────────────────────────────────────
    if tool == "chat":
        yield {"data": _emit("progress", step="memory", detail="🧠 Looking up scan results...")}
        reply = await answer_with_memory(
            message=message,
            chat_history=chat_history,
            latest_scan=latest_scan,
            current_url=current_url,
        )
        logger.info("Chat → memory answer  elapsed=%dms",
                    int((time.monotonic() - t_total) * 1000))
        yield {"data": _emit("complete", response=reply, tool_used="chat", raw_data={})}
        return

    # ── Scan tools ────────────────────────────────────────────────────────────
    yield {"data": _emit("progress", step="routing_done",
                         detail=f"✅ Got it — {intent_msg}")}

    page_context = _detect_framework(page_data)
    logger.info("Chat → framework=%s platform=%s",
                page_context["framework"], page_context["platform"])

    # ── Country parsing (for geocheck/both) ───────────────────────────────────
    countries = []
    if tool in ("geocheck", "both"):
        parsed = parse_countries(message)

        # Unsupported country
        if isinstance(parsed, dict) and parsed.get("unsupported"):
            country_name = parsed["country_name"]
            reply = (
                f"**{country_name}** isn't available as a TinyFish proxy location yet.\n\n"
                f"Supported countries: {SUPPORTED_LIST}"
            )
            yield {"data": _emit("complete", response=reply, tool_used="off_topic", raw_data={})}
            return

        countries = parsed
        n   = len(countries)
        ies = "y" if n == 1 else "ies"
        logger.info("Chat → countries=%s", [c["code"] for c in countries])
        yield {"data": _emit("progress", step="geo_start",
                             detail=f"🌍 Spinning up stealth browsers in {n} countr{ies}...")}

    results = {}

    # ── GhostScan ─────────────────────────────────────────────────────────────
    if tool in ("ghostscan", "both"):
        yield {"data": _emit("progress", step="ghostscan_start",
                             detail="🔍 Injecting scanner into page DOM...")}

        has_data = page_data and any([
            page_data.get("inline_scripts"),
            page_data.get("window_keys"),
            page_data.get("local_storage"),
            page_data.get("session_storage"),
            page_data.get("network_headers"),
            page_data.get("network_urls"),
            page_data.get("cookies"),
        ])

        if has_data:
            yield {"data": _emit("progress", step="ghostscan_scan",
                                 detail=f"🔬 Running {PATTERN_COUNT} pattern checks...")}
            gs_result = await run_ghostscan_logic(page_data)

            if gs_result.get("warning"):
                yield {"data": _emit("progress", step="ghostscan_done",
                                     detail=f"⚠️ {gs_result['warning']}")}
            else:
                total    = gs_result.get("total", 0)
                critical = gs_result.get("critical_count", 0)
                high     = gs_result.get("high_count", 0)

                if total > 0:
                    yield {"data": _emit("progress", step="ghostscan_recs",
                                         detail="💡 Generating fix recommendations...")}
                    fix_recs = await generate_fix_recommendations(
                        gs_result.get("findings", []), page_context,
                    )
                    fix_map = {r["type"]: r.get("fix", "") for r in fix_recs}
                    for finding in gs_result.get("findings", []):
                        if finding["type"] in fix_map:
                            finding["fix"] = fix_map[finding["type"]]

                parts = []
                if critical: parts.append(f"{critical} critical")
                if high:     parts.append(f"{high} high")
                detail = (f"⚠️ Found {total} issue(s): {', '.join(parts)}."
                          if total else "✅ GhostScan complete — no secrets detected.")
                yield {"data": _emit("progress", step="ghostscan_done", detail=detail)}

            results["ghostscan"] = gs_result
            logger.info("Chat → GhostScan done  total=%d  critical=%d",
                        gs_result.get("total", 0), gs_result.get("critical_count", 0))
        else:
            results["ghostscan"] = {
                "error": True,
                "message": "No page data received. Reload the tab and try again.",
                "code": "NO_PAGE_DATA",
                "findings": [], "total": 0,
                "critical_count": 0, "high_count": 0,
                "warning_count": 0, "safe_count": 0,
            }
            yield {"data": _emit("progress", step="ghostscan_done",
                                 detail="⚠️ Could not read page DOM — reload the tab and retry.")}

    # ── GeoCheck ──────────────────────────────────────────────────────────────
    if tool in ("geocheck", "both"):
        if not current_url:
            results["geocheck"] = {"error": True, "message": "No URL.", "code": "NO_URL"}
            yield {"data": _emit("progress", step="geo_done",
                                 detail="⚠️ No URL — please open a tab first.")}
        else:
            for c in countries:
                yield {"data": _emit("progress", step="geo_country",
                                     detail=f"📡 Launched → {c['flag']} {c['name']}")}

            geo_results_list: list = []
            geo_queue: asyncio.Queue = asyncio.Queue()

            async def on_geo_result(r: dict):
                await geo_queue.put(r)

            geo_task = asyncio.create_task(
                run_sse_concurrent(current_url, countries, on_geo_result)
            )

            STATUS_ICON = {"pass":"✅","fail":"❌","timeout":"⏱️","error":"⚠️"}

            while len(geo_results_list) < len(countries):
                try:
                    r = await asyncio.wait_for(geo_queue.get(), timeout=130)
                    geo_results_list.append(r)
                    done      = len(geo_results_list)
                    remaining = len(countries) - done
                    icon      = STATUS_ICON.get(r.get("status","error"), "⚠️")
                    top_issue = (r.get("issues") or [""])[0]
                    status_text = top_issue[:50] if top_issue else r.get("status","unknown")

                    yield {"data": _emit("geo_result", data=r)}
                    yield {"data": _emit("progress", step="geo_result",
                                         detail=f"{icon} {r['flag']} {r['name']} — {status_text}")}
                    if remaining > 0:
                        yield {"data": _emit("progress", step="geo_waiting",
                                             detail=f"⏳ Waiting... ({done}/{len(countries)} done)")}
                except asyncio.TimeoutError:
                    logger.warning("Chat → geo queue timeout  received=%d", len(geo_results_list))
                    break

            await geo_task

            passing    = sum(1 for r in geo_results_list if r.get("status") == "pass")
            issues_all = [
                f"{r['flag']} {r['country']}: {issue}"
                for r in geo_results_list
                for issue in (r.get("issues") or [])
            ]
            results["geocheck"] = {
                "url":     current_url,
                "results": geo_results_list,
                "passing": passing,
                "total":   len(countries),
                "summary": f"{passing}/{len(countries)} passing",
                "issues":  issues_all,
            }
            yield {"data": _emit("progress", step="geo_done",
                                 detail=f"✅ GeoCheck done — {passing}/{len(countries)} passing.")}
            logger.info("Chat → GeoCheck done  %d/%d passing", passing, len(countries))

    # ── Summarize ─────────────────────────────────────────────────────────────
    summary_parts = []

    if "ghostscan" in results and not results["ghostscan"].get("error"):
        yield {"data": _emit("progress", step="summarizing", detail="✍️  Summarizing...")}
        summary_parts.append(await summarize_ghostscan(results["ghostscan"], focus))

    if "geocheck" in results and not results["geocheck"].get("error"):
        yield {"data": _emit("progress", step="summarizing_geo", detail="✍️  Analysing geo results...")}
        summary_parts.append(await summarize_geocheck(results["geocheck"], focus))

    if "ghostscan" in results and results["ghostscan"].get("error"):
        summary_parts.append("⚠️ GhostScan: " + results["ghostscan"].get("message", "Failed."))
    if "geocheck" in results and results["geocheck"].get("error"):
        summary_parts.append("⚠️ GeoCheck: " + results["geocheck"].get("message", "Failed."))

    final_response = "\n\n".join(summary_parts) or intent_msg or "Scan complete."
    elapsed = int((time.monotonic() - t_total) * 1000)
    logger.info("Chat → complete  tool=%s  elapsed=%dms", tool, elapsed)

    # Strip inline_scripts from ghostscan raw_data before sending over SSE.
    # They can be hundreds of KB and cause the complete event to be split
    # across multiple SSE chunks, breaking the popup's JSON.parse.
    safe_results = {}
    for k, v in results.items():
        if k == "ghostscan" and isinstance(v, dict):
            safe_results[k] = {key: val for key, val in v.items() if key != "inline_scripts"}
        else:
            safe_results[k] = v

    yield {"data": _emit("complete",
                         response=final_response,
                         tool_used=tool,
                         raw_data=safe_results,
                         page_context=page_context)}


@router.post("/chat")
async def chat(request: ChatRequest):
    logger.info("Chat → incoming  url=%s  message=%r", request.current_url, request.message)
    return EventSourceResponse(_stream(request))