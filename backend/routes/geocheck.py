import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from services.tinyfish import run_concurrent, run_sse_concurrent
from utils.country_parser import ALL_COUNTRIES, parse_countries

logger = logging.getLogger("deploylens.geocheck")
router = APIRouter()


class GeoCheckRequest(BaseModel):
    url: str
    countries: Optional[list] = None   # pre-parsed list injected by /chat; None → all 7


async def run_geocheck_logic(url: str, countries: list = None) -> dict:
    """
    Non-streaming GeoCheck used by /chat.
    countries: list of country dicts; defaults to ALL_COUNTRIES.
    All requests fire concurrently via asyncio.gather.
    """
    if not countries:
        countries = ALL_COUNTRIES

    logger.info("GeoCheck logic → url=%s  countries=%s", url, [c["code"] for c in countries])
    t0 = time.monotonic()

    results = await run_concurrent(url, countries)

    elapsed = int((time.monotonic() - t0) * 1000)
    passing = sum(1 for r in results if r.get("status") == "pass")
    issues  = [
        f"{r['flag']} {r['country']}: {issue}"
        for r in results
        for issue in (r.get("issues") or [])
    ]

    summary = f"{passing}/{len(results)} passing"
    if issues:
        summary += f", {len(issues)} issue(s) found"

    logger.info("GeoCheck logic → %s  elapsed=%dms", summary, elapsed)

    return {
        "url":      url,
        "results":  results,
        "passing":  passing,
        "total":    len(results),
        "summary":  summary,
        "issues":   issues,
    }


@router.post("/geocheck")
async def geocheck_stream(request: GeoCheckRequest):
    """
    SSE streaming endpoint — streams each country result as it arrives.
    All country checks fire concurrently; results arrive in completion order.
    """
    countries = request.countries or ALL_COUNTRIES
    url       = request.url
    logger.info("GeoCheck SSE → url=%s  countries=%s", url, [c["code"] for c in countries])

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        results = []

        async def on_result(r: dict):
            await queue.put(r)

        # Fire all concurrent SSE tasks in background
        task = asyncio.create_task(run_sse_concurrent(url, countries, on_result))

        total = len(countries)
        sent  = 0

        TIMEOUT = 130
        while sent < total:
            try:
                result = await asyncio.wait_for(queue.get(), timeout=TIMEOUT)
                results.append(result)
                sent += 1
                yield {"data": json.dumps(result)}
            except asyncio.TimeoutError:
                logger.warning("GeoCheck SSE → queue timeout after %ds", TIMEOUT)
                break

        await task

        passing    = sum(1 for r in results if r.get("status") == "pass")
        issues_all = [
            f"{r['flag']} {r['country']}: {issue}"
            for r in results
            for issue in (r.get("issues") or [])
        ]

        yield {
            "data": json.dumps({
                "type":    "complete",
                "summary": f"{passing}/{total} passing" + (f", {len(issues_all)} issue(s)" if issues_all else ""),
                "issues":  issues_all,
                "results": results,
            })
        }

    return EventSourceResponse(event_generator())
