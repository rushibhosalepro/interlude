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

PROMPT = """Write one line of audio description for a blind listener.

It gets spoken aloud into a {seconds:.1f} second gap in the audio, so it must be
at most {budget} words. That is a hard limit.

The visual facts to convey:
{facts}

Dialogue immediately before this moment: {before}
Dialogue immediately after: {after}

Write it the way a person would say it out loud.

- A complete sentence with a verb. Never a bare fragment, and never a list of
  labels read out on their own.
- Say what the thing IS before its content: "an end card reads", "a diagram
  shows", "she writes on the whiteboard". Someone who only hears words read off
  a screen has no idea what they are looking at, which is the whole problem.
- No quotation marks. They are silent, so they mark nothing and only waste
  characters.
- Present tense, plain and factual. Skip adjectives that carry no information.
- Do not repeat anything the dialogue already said.

Good:  The video ends on an end card reading: onsite, built with GPT-5.6.
Good:  He sketches a binary tree on the whiteboard.
Bad:   'onsite' and 'Built with GPT-5.6'.
Bad:   Fades to black. Text appears.
Bad:   On black, onsite above Built with GPT-5.6.

The bad ones are bad because a listener cannot tell what they are hearing about.
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

    async def _attempt() -> str:
        result = await asyncio.to_thread(_post)
        if should_retry_status(result.status_code):
            raise RetryableStatus(f"gemini returned {result.status_code}")
        if result.status_code != 200:
            raise WriteError(
                f"gemini returned {result.status_code}: {result.text[:300]}"
            )

        # Gemini occasionally returns malformed JSON even with
        # responseMimeType=application/json. Regenerating is the fix; failing the
        # whole job over one bad response is not.
        try:
            raw = result.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw)["text"].strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise RetryableStatus(f"unparseable response: {exc}") from exc

    text = await with_retry(_attempt, label="gemini write")

    if not text:
        raise WriteError("model returned an empty description")

    return text
