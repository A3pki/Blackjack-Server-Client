"""Gemini-powered chat moderation filter.

Uses the free Gemini REST API (gemini-2.0-flash-lite) to classify each
chat message as ALLOW or BLOCK before it is broadcast to other players.

The call is made synchronously (blocking) from the client-handler thread.
Round-trip latency is typically <400 ms on the free tier.

Fallback behaviour
------------------
- If the API key is absent → ALLOW (filter silently disabled).
- If the request times out or returns a network error → ALLOW.
- If the model returns an unparseable response → ALLOW.
- If the API returns 429 (rate-limit / quota) → ALLOW, and a cooldown
  period is applied so we don't hammer the endpoint further.

The game is never broken by a moderation outage.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

# gemini-2.0-flash-lite: free tier 1 500 req/day, 30 req/min
_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash-lite:generateContent?key={key}"
)
_TIMEOUT_S = 8  # seconds per moderation call

# ---------------------------------------------------------------------------
# Rate / quota guard
# Enforces at most 1 call per second (well under the 30 rpm free limit).
# If the API returns 429 we back off for the duration it suggests.
# ---------------------------------------------------------------------------
_rate_lock = threading.Lock()
_last_call_ts: float = 0.0        # monotonic time of last successful call
_backoff_until: float = 0.0       # monotonic time until we stop skipping calls
_MIN_INTERVAL_S = 1.0             # minimum gap between calls

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a chat moderation assistant for an online multiplayer Blackjack card-game.

Classify the player message and decide whether to show it to other players.

BLOCK the message if it contains any of:
  - profanity, slurs, or vulgar language
  - hate speech targeting any group (race, gender, religion, nationality, etc.)
  - threats, harassment, or personal attacks
  - sexually explicit content
  - promotion of violence, illegal activity, or self-harm
  - spam, phishing links, or advertising
  - politically charged debate or divisive arguments
  - excessive ALL-CAPS yelling (full sentences in capitals)

ALLOW everything else: normal game chat, mild friendly trash-talk,
strategy discussion, congratulations, questions about the game.

Reply with ONLY a raw JSON object (no markdown, no extra text):
{"verdict": "ALLOW", "reason": "brief reason"}
or
{"verdict": "BLOCK", "reason": "brief reason"}
"""


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def is_allowed(message: str) -> Tuple[bool, str]:
    """Return ``(True, reason)`` if the message should be broadcast.

    Never raises — falls back to ALLOW on any error or quota issue.
    """
    if not _API_KEY:
        log.debug("chat_filter: GEMINI_API_KEY not set — moderation disabled")
        return True, "moderation disabled (no API key)"

    global _backoff_until
    now = time.monotonic()
    if now < _backoff_until:
        remaining = _backoff_until - now
        log.debug("chat_filter: in backoff (%.0f s remaining) — defaulting ALLOW", remaining)
        return True, "moderation in backoff"

    try:
        verdict, reason = _call_gemini(message)
    except _QuotaError as exc:
        # Respect the retry-after delay from the API response.
        with _rate_lock:
            _backoff_until = time.monotonic() + exc.retry_after_s
        log.warning(
            "chat_filter: quota/rate-limit hit — backing off %.0f s",
            exc.retry_after_s,
        )
        return True, "moderation unavailable (quota)"
    except Exception as exc:
        log.warning("chat_filter: API error (%s) — defaulting ALLOW", exc)
        return True, "moderation unavailable"

    allowed = verdict.upper() == "ALLOW"
    log.info(
        "chat_filter: %s | reason=%r | msg=%r",
        verdict, reason, message[:60],
    )
    return allowed, reason


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _QuotaError(Exception):
    def __init__(self, retry_after_s: float = 60.0) -> None:
        super().__init__(f"quota/rate-limit (retry after {retry_after_s:.0f}s)")
        self.retry_after_s = retry_after_s


def _call_gemini(message: str) -> Tuple[str, str]:
    """Make one moderation call to Gemini; return (verdict, reason)."""
    global _last_call_ts
    # Enforce minimum interval between calls.
    with _rate_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_S - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.monotonic()

    url = _API_URL.format(key=_API_KEY)
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {
            "temperature": 0,       # deterministic classification
            "maxOutputTokens": 64,
        },
    }

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        body_text = body_bytes.decode("utf-8", errors="replace")
        if exc.code == 429:
            # Try to extract retryDelay from the response body.
            retry_s = _parse_retry_delay(body_text)
            raise _QuotaError(retry_s) from exc
        raise RuntimeError(f"HTTP {exc.code}: {body_text[:200]}") from exc

    return _parse_model_response(raw)


def _parse_retry_delay(body_text: str) -> float:
    """Extract the retryDelay seconds from a 429 response body."""
    try:
        data = json.loads(body_text)
        details = data.get("error", {}).get("details", [])
        for detail in details:
            delay = detail.get("retryDelay", "")
            # Format is like "44s" or "44.798015111s"
            m = re.search(r"([\d.]+)s", str(delay))
            if m:
                return min(float(m.group(1)) + 5, 120)  # cap at 2 min
    except Exception:
        pass
    return 65.0  # safe default


def _parse_model_response(raw: str) -> Tuple[str, str]:
    """Extract (verdict, reason) from the Gemini API JSON envelope."""
    try:
        outer = json.loads(raw)
        text = outer["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected response shape: {exc}") from exc

    # Strip accidental markdown fences the model may wrap around the JSON.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        parsed = json.loads(text)
        verdict = str(parsed.get("verdict", "ALLOW")).upper()
        reason = str(parsed.get("reason", ""))
        if verdict not in ("ALLOW", "BLOCK"):
            verdict = "ALLOW"
        return verdict, reason
    except json.JSONDecodeError:
        log.warning(
            "chat_filter: could not parse model reply %r — defaulting ALLOW",
            text[:80],
        )
        return "ALLOW", "parse error"
