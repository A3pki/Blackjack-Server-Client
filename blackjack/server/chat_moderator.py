"""Gemini-powered chat moderator.

Screens player chat messages for vulgar, hateful, or offensive content.
Requires the ``GEMINI_API_KEY`` environment variable.

If the key is absent the moderator runs in **pass-through** mode —
all messages are allowed and a one-time warning is logged, so the game
remains fully playable without an API key.
"""

from __future__ import annotations

import logging
import os
from typing import Tuple

log = logging.getLogger(__name__)

_WARN_LOGGED = False

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


def _build_client():
    """Create and return a configured Gemini client."""
    from google import genai  # type: ignore

    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


class ChatModerator:
    """AI-powered chat filter backed by Gemini Flash.

    Create one instance per server (or one module-level singleton).
    The underlying SDK client is created lazily on the first ``check()``
    call so startup is not delayed when moderation is disabled.

    Example::

        moderator = ChatModerator()
        allowed, reason = moderator.check("your message here")
        if not allowed:
            handler.send("error", {"message": reason})
    """

    def __init__(self) -> None:
        global _WARN_LOGGED
        self._enabled = bool(os.environ.get("GEMINI_API_KEY", "").strip())
        if not self._enabled and not _WARN_LOGGED:
            log.warning(
                "GEMINI_API_KEY is not set – AI chat moderation is disabled. "
                "Set the variable and restart the server to enable content filtering."
            )
            _WARN_LOGGED = True
        self._model = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def check(self, message: str) -> Tuple[bool, str]:
        """Classify *message* and return ``(allowed, reason)``.

        * ``allowed=True``  → broadcast the message as normal.
        * ``allowed=False`` → send the reason back to the sender only.

        If moderation is disabled **or** the API call fails for any reason
        (network error, quota exhausted, etc.) the message is allowed through
        so the game remains playable.
        """
        if not self._enabled:
            return True, "moderation disabled"

        try:
            if self._model is None:
                self._model = _build_client()
            from google.genai import types as genai_types  # type: ignore
            response = self._model.models.generate_content(
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
            # Anything that is not an unambiguous ALLOW is treated as a block.
            return False, "הודעתך נחסמה בשל תוכן פוגעני או לא הולם."
        except Exception as exc:
            log.warning(
                "Gemini moderation call failed (%s) – message passed through.", exc
            )
            return True, "moderation error – passed through"
