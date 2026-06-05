"""AI chat filter — screens messages for offensive content using Gemini Flash.

If GEMINI_API_KEY isn't set, the moderator just lets everything through
and logs a warning. The game still works fine without it.
"""

from __future__ import annotations

import logging
import os
from typing import Tuple

log = logging.getLogger(__name__)

_warned_about_key = False  # only log the missing-key warning once

_SYSTEM_PROMPT = """\
You are a strict content moderator for an online multiplayer card game chat.

Your ONLY job is to classify a single player message as ALLOW or BLOCK.

BLOCK the message if it contains ANY of the following — even partial spellings,
letter substitutions (3 for e, @ for a, etc.), or soft/hard variants:
- Racial or ethnic slurs of ANY kind (e.g. the n-word in any form, variants, or euphemisms)
- Sexual words or content (e.g. "sex", "porn", genitalia, explicit acts)
- Profanity / swear words (f-word, s-word, etc.)
- Hate speech targeting race, religion, gender, sexuality, nationality, or any group
- Threats, calls to violence, or wishes of harm
- Harassment or personal attacks

ALLOW the message ONLY if it is clearly innocent game chat such as:
- Game phrases: "hit", "stand", "nice hand", "good game", "gg", "bad luck"
- Numbers, betting talk, strategy
- Friendly small talk with no offensive words

When in doubt, BLOCK.

Reply with exactly one word — ALLOW or BLOCK — no punctuation, no explanation.\
"""


def _make_gemini_client():
    """Create and return a configured Gemini client using the API key from env."""
    from google import genai  # type: ignore
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


class ChatModerator:
    """AI-powered chat filter backed by Gemini Flash.

    Instantiate once per server (or use the module-level singleton in
    client_handler.py). The Gemini client is created lazily on the first
    check() call so the server starts up fast even without a key.

    Usage:
        moderator = ChatModerator()
        allowed, reason = moderator.check("some message here")
        if not allowed:
            handler.send("error", {"message": reason})
    """

    def __init__(self) -> None:
        """Set up the moderator. Warns once if GEMINI_API_KEY is missing."""
        global _warned_about_key
        self._enabled = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        if not self._enabled and not _warned_about_key:
            log.warning(
                "GEMINI_API_KEY not set — AI chat moderation is disabled. "
                "Set the variable and restart the server to enable filtering."
            )
            _warned_about_key = True
        self._client = None  # created on first use

    @property
    def enabled(self) -> bool:
        """True when moderation is active (key is set)."""
        return self._enabled

    def check(self, message: str) -> Tuple[bool, str]:
        """Ask Gemini whether a message is OK to broadcast.

        Returns (True, "ok") if allowed, (False, reason) if blocked.
        If moderation is disabled or the API call fails, the message is
        allowed through so the game doesn't break when the API is down.
        """
        if not self._enabled:
            return True, "moderation disabled"

        try:
            if self._client is None:
                self._client = _make_gemini_client()
            from google.genai import types as genai_types  # type: ignore
            response = self._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=message,
                config=genai_types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    max_output_tokens=8,
                ),
            )
            verdict = (response.text or "").strip().upper()
            if verdict != "BLOCK":
                return True, "ok"
            # Anything other than a clear ALLOW gets blocked.
            return False, "הודעתך נחסמה בשל תוכן פוגעני או לא הולם."
        except Exception as exc:
            log.warning("Gemini moderation failed (%s) — message passed through.", exc)
            return True, "moderation error – passed through"
