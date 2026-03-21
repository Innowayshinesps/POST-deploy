import json
import logging
import os
import re

from groq import AsyncGroq

logger = logging.getLogger("deploylens.intent_router")
client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

PRIMARY_MODEL  = "llama-3.1-8b-instant"
FALLBACK_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are the routing brain of POST-deploy, a developer security Chrome extension.

Classify the user message into ONE of these 5 categories:

  ghostscan  — user wants to scan the current page for exposed secrets, API keys, tokens, credentials
  geocheck   — user wants to RUN a new geo test from a specific country/region (NEW scan)
  both       — "safe to launch?", "scan everything", "full scan", "pre-launch"
  chat       — follow-up questions about previous results, questions using "that/this/it/the issue"
               ANY question that references something already shown or asks for explanation/fix
               Examples: "how to secure that", "why so?", "how to resolve this",
               "what does it mean?", "why did it fail?", "how to fix the issue",
               "what should i do?", "tell me more", "explain", "what next?"
  off_topic  — pure greetings ("hi","hello"), "ok", "thanks", jokes, completely unrelated

CRITICAL RULES:
1. If message uses "that/this/it/the issue/the problem/the key/the error" to reference previous results → ALWAYS "chat"
2. "how to [verb] that/this/it/the X" → ALWAYS "chat"
3. "why so", "why is that", "why did", "why not", "why does" → ALWAYS "chat"
4. "what should i do" / "what now" / "what next" → ALWAYS "chat"
5. Single-word acknowledgments: "ok", "thanks", "sure", "cool" → "off_topic"
6. Only "geocheck" when user names a country for a NEW test
7. Generic "security" words (secure, fix, resolve) WITH pronouns (this, that, it) → "chat" NOT ghostscan

Return ONLY valid JSON, no markdown:
{"tool":"ghostscan"|"geocheck"|"both"|"chat"|"off_topic","message":"...","focus":null,"chat_reply":null}

Examples:
"any api keys exposed?" → {"tool":"ghostscan","message":"Scanning for exposed API keys.","focus":"api keys","chat_reply":null}
"check for germany" → {"tool":"geocheck","message":"Testing from Germany.","focus":"germany","chat_reply":null}
"safe to launch?" → {"tool":"both","message":"Running full pre-launch checks.","focus":null,"chat_reply":null}
"how to secure that" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"how to resolve this" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"how to resolve the issue" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"why so??" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"why did it fail?" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"what should i do?" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"how do i fix that?" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"is it serious?" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"tell me more" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"what next?" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"explain" → {"tool":"chat","message":"","focus":null,"chat_reply":null}
"ok" → {"tool":"off_topic","message":"","focus":null,"chat_reply":"Got it!"}
"thanks" → {"tool":"off_topic","message":"","focus":null,"chat_reply":"You're welcome! Let me know if you need another scan."}"""


# ── Pre-check regex patterns ───────────────────────────────────────────────────
# These catch referential follow-ups BEFORE the LLM sees them.
# Pattern: action verb + referential pronoun, or question words with context pronouns.
_FOLLOWUP_PATTERNS = [
    # "how to/do I/can I [verb] this/that/it/the X"
    r"\bhow\s+(to|do\s+i|can\s+i)\b.{0,60}\b(this|that|it|the\s+\w+)\b",
    # "[verb] this/that/it/the issue/problem/key/error"
    r"\b(fix|resolve|secure|handle|address|prevent|rotate|remove|update|store)\b.{0,40}\b(this|that|it|the\s+\w+)\b",
    # "why so / why is that / why did / why not / why does"
    r"\bwhy\s+(so|is\s+that|did|does|not|isn't|doesn't|would)\b",
    r"^why\s+so[?!.\s]*$",
    # "what should I do / what now / what next / what do I do"
    r"\bwhat\s+(should|now|next|do\s+i|can\s+i)\b",
    # "what does that/this/it mean"
    r"\bwhat\s+does\s+(that|this|it)\b",
    # "is it serious/bad/critical/fine/safe"
    r"^is\s+it\s+(serious|critical|bad|dangerous|fine|ok|safe|a\s+problem)[?!.]*$",
    # "how serious/bad/critical is it"
    r"\bhow\s+(serious|bad|critical|dangerous|important)\b",
    # Pure explain/elaborate
    r"^(explain|elaborate|tell\s+me\s+more|more\s+info|more\s+details)[?!.\s]*$",
]
_FOLLOWUP_RE = [re.compile(p, re.IGNORECASE) for p in _FOLLOWUP_PATTERNS]


def _is_followup(message: str) -> bool:
    return any(pat.search(message.strip()) for pat in _FOLLOWUP_RE)


async def _call_model(model: str, message: str, current_url: str) -> dict:
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"URL: {current_url}\nUser: {message}"},
        ],
        temperature=0.05,
        max_tokens=200,
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    result.setdefault("tool",       "ghostscan")
    result.setdefault("message",    "")
    result.setdefault("focus",      None)
    result.setdefault("chat_reply", None)
    return result


async def route_intent(message: str, current_url: str) -> dict:
    logger.info("Routing intent | url=%s | message=%r", current_url, message)

    # Pre-check: catch referential follow-ups before the LLM can misclassify them
    if _is_followup(message):
        logger.info("Intent pre-classified as chat (referential follow-up pattern matched)")
        return {"tool": "chat", "message": "", "focus": None, "chat_reply": None}

    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            result = await _call_model(model, message, current_url)
            logger.info("Intent resolved → model=%s tool=%s focus=%s",
                        model, result.get("tool"), result.get("focus"))
            return result
        except Exception as e:
            logger.warning("Intent routing failed model=%s error=%s", model, e)

    logger.warning("All models failed — keyword fallback for %r", message)
    return _keyword_fallback(message)


def _keyword_fallback(message: str) -> dict:
    text = message.lower().strip()

    OFF_EXACT = {
        "sure", "ok", "okay", "yes", "no", "nope", "yep", "yeah",
        "thanks", "thank you", "cool", "nice", "great", "got it",
        "hi", "hello", "hey", "bye", "lol", "haha", "k", "👍",
    }
    if text in OFF_EXACT:
        return {"tool": "off_topic", "message": "", "focus": None,
                "chat_reply": "I'm a security scanner. Try: 'any api keys exposed?' or 'check germany'."}

    # Referential + context question signals → chat
    CHAT_PHRASES = [
        "does it", "did it", "why so", "why is", "why did", "why not", "why does",
        "how do", "how to", "how can", "how serious", "how bad",
        "what does", "what should", "what now", "what next", "what about",
        "explain", "tell me more", "is it serious", "is it bad",
        "fix this", "fix that", "resolve this", "resolve that",
        "secure this", "secure that", "the issue", "the problem", "the error",
    ]
    if any(p in text for p in CHAT_PHRASES):
        return {"tool": "chat", "message": "", "focus": None, "chat_reply": None}

    RESCAN_KW = [
        "scan this", "check this", "this site", "this page",
        "scan here", "scan now", "any issues", "any leaks",
        "check for any", "scan for any",
    ]
    GEO_RUN_KW = [
        "check from", "check for", "test from", "scan from", "geo check", "geo scan",
        "germany", "german", "france", "french", "japan", "japanese",
        "britain", "england", "australia", "australian", "canada", "canadian",
        "america", "usa", "united states", "europe", "european", "asia",
    ]
    BOTH_KW  = ["safe to launch", "scan everything", "full scan", "pre-launch"]
    GHOST_KW = ["api key", "api leak", "any leak", "key exposed", "secret exposed",
                "token exposed", "exposed", "credential", "stripe", "aws", "github",
                "openai", "razorpay", "vulnerability"]

    if any(kw in text for kw in RESCAN_KW):
        return {"tool": "ghostscan", "message": "Scanning the current page.", "focus": None, "chat_reply": None}
    if any(kw in text for kw in BOTH_KW):
        return {"tool": "both", "message": "Running full security and geo scan.", "focus": None, "chat_reply": None}
    if any(kw in text for kw in GEO_RUN_KW):
        return {"tool": "geocheck", "message": "Testing geo availability.", "focus": None, "chat_reply": None}
    if any(kw in text for kw in GHOST_KW):
        return {"tool": "ghostscan", "message": "Scanning for exposed secrets.", "focus": None, "chat_reply": None}

    # Short question with no scan keywords → likely a follow-up
    if "?" in text and len(text.split()) <= 7:
        return {"tool": "chat", "message": "", "focus": None, "chat_reply": None}

    return {"tool": "off_topic", "message": "", "focus": None,
            "chat_reply": "I'm a security tool. Try: 'any api keys exposed?' or 'check germany'."}