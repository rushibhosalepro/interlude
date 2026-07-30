"""Write the narration for one gap, to a word budget.

Text only, no video, so this is much cheaper than the analyse call. The facts
were already extracted there; this stage only turns them into a sentence that
fits.
"""

import asyncio
import json
import logging
import os

import httpx

from worker.retry import RetryableStatus, should_retry_status, with_retry

logger = logging.getLogger(__name__)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

PROMPT = """Write one piece of audio description for a blind viewer.

These are the essential visual facts to convey:
{facts}

Dialogue immediately before this moment: {before}
Dialogue immediately after: {after}

Rules:
- At most {budget} words. This is a hard limit, it must be spoken aloud in {seconds:.1f} seconds.
- Present tense. Plain, factual, neutral.
- Do not say "we see", "the screen shows", "the video displays". Just state what happens.
- Do not repeat anything already said in the dialogue above.
- No adjectives unless they carry essential information.
- One sentence if possible. Never more than two.
{retry}
Reply with JSON only: {{"text": "..."}}"""

RETRY_NOTE = """
Your previous attempt was "{previous}"
Spoken aloud that took {actual:.2f}s, but only {target:.2f}s is available.
Write it shorter. Cut the least essential detail first.
"""


class WriteError(RuntimeError):
    pass


async def write_description(
    facts: list[str],
    budget_words: int,
    seconds: float,
    before: str = "",
    after: str = "",
    previous: str | None = None,
    actual: float | None = None,
) -> str:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise WriteError("GOOGLE_API_KEY is not set")

    retry = ""
    if previous and actual:
        retry = RETRY_NOTE.format(previous=previous, actual=actual, target=seconds)

    prompt = PROMPT.format(
        facts="\n".join(f"- {f}" for f in facts),
        budget=max(budget_words, 2),
        seconds=seconds,
        before=before or "(nothing)",
        after=after or "(nothing)",
        retry=retry,
    )

    def _post() -> httpx.Response:
        return httpx.post(
            f"{ENDPOINT}/{MODEL}:generateContent",
            params={"key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.4,
                },
            },
            timeout=120,
        )

    async def _attempt() -> httpx.Response:
        result = await asyncio.to_thread(_post)
        if should_retry_status(result.status_code):
            raise RetryableStatus(f"gemini returned {result.status_code}")
        return result

    response = await with_retry(_attempt, label="gemini write")

    if response.status_code != 200:
        raise WriteError(f"gemini returned {response.status_code}: {response.text[:300]}")

    try:
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = json.loads(raw)["text"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise WriteError(f"could not parse gemini response: {exc}") from exc

    if not text:
        raise WriteError("model returned an empty description")

    return text
