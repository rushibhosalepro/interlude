"""Decide what to narrate, using Gemini's video understanding.

This is the filter and the fact extraction in one call, which is what
ARCHITECTURE.md calls Stage 0. The model watches the video, looks at each silent
gap, and answers two questions in order:

  1. does anything visually essential happen here that the dialogue misses?
  2. if so, what exactly?

Most gaps should come back "skip". Over-narration is the classic failure of bad
audio description, so the prompt pushes hard against it.

Sends the video file directly rather than extracted keyframes: it needs no local
media codec, and the model sees motion rather than a single still.
"""

import asyncio
import base64
import json
import logging
import os
from pathlib import Path

import httpx

from worker.retry import RetryableStatus, should_retry_status, with_retry

logger = logging.getLogger(__name__)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

# inline base64 is capped by the request size. beyond this the Files API is
# needed, which is a separate upload step.
MAX_INLINE_BYTES = 18 * 1024 * 1024

PROMPT = """You are writing audio description for blind viewers of this video.

The dialogue is already audible to them. Your job is ONLY to cover visual
information that the words do not convey.

Below are the silent gaps in this video. For each one, look at what is on screen
during that time range and decide whether it needs narration.

Say SKIP unless a viewer would genuinely miss something. Specifically skip when:
- nothing changes, or people simply remain where they were
- what is shown was already said out loud in the surrounding dialogue
- the only content is decorative, a logo, or a title the speaker reads aloud

Say FILL only when something visually essential happens: text or a diagram
appears that is not read aloud, someone demonstrates something, a scene changes,
a result is revealed.

When you say FILL, list the essential visual facts as short factual phrases.
No interpretation, no adjectives, no "we see". Just what is there.

Gaps:
{gaps}

Surrounding dialogue for context:
{dialogue}

Reply with JSON only, in this exact shape:
{{"decisions": [
  {{"gapId": "gap-001", "action": "fill", "facts": ["...", "..."], "reason": "..."}},
  {{"gapId": "gap-002", "action": "skip", "facts": [], "reason": "..."}}
]}}"""


class AnalysisError(RuntimeError):
    pass


def _dialogue_around(transcript: dict, gaps: list[dict], window: float = 8.0) -> str:
    """The words spoken just before and after each gap, so the model can tell
    whether the visuals were already covered out loud."""
    words = transcript.get("words") or []
    lines = []

    for gap in gaps:
        before = [
            w["word"] for w in words if gap["start"] - window <= w["end"] <= gap["start"]
        ]
        after = [
            w["word"] for w in words if gap["end"] <= w["start"] <= gap["end"] + window
        ]
        lines.append(
            f"{gap['id']}:\n"
            f"  before: {' '.join(before) or '(nothing)'}\n"
            f"  after:  {' '.join(after) or '(nothing)'}"
        )

    return "\n".join(lines)


def _gap_list(gaps: list[dict]) -> str:
    return "\n".join(
        f"  {g['id']}: {g['start']:.2f}s to {g['end']:.2f}s "
        f"({g['duration']:.2f}s of silence, room for about {g['wordBudget']} words)"
        for g in gaps
    )


async def analyse(video_path: str, gaps: list[dict], transcript: dict) -> dict:
    """Fill or skip, plus the essential visual facts, for every gap."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise AnalysisError("GOOGLE_API_KEY is not set")

    if not gaps:
        return {"decisions": [], "model": MODEL, "provider": "google"}

    path = Path(video_path)
    size = path.stat().st_size
    if size > MAX_INLINE_BYTES:
        raise AnalysisError(
            f"{path.name} is {size / 1_048_576:.0f} MB, too big to inline. The "
            "pipeline sends a 480p 2fps silent proxy rather than the master, so "
            "hitting this means either a very long recording or a proxy encode "
            "that did not run."
        )

    prompt = PROMPT.format(
        gaps=_gap_list(gaps), dialogue=_dialogue_around(transcript, gaps)
    )

    def _post() -> httpx.Response:
        encoded = base64.b64encode(path.read_bytes()).decode()
        return httpx.post(
            f"{ENDPOINT}/{MODEL}:generateContent",
            params={"key": api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": "video/mp4", "data": encoded}},
                            {"text": prompt},
                        ]
                    }
                ],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    # low temperature: we want consistent factual output, not prose
                    "temperature": 0.2,
                },
            },
            timeout=300,
        )

    async def _attempt() -> httpx.Response:
        result = await asyncio.to_thread(_post)
        if should_retry_status(result.status_code):
            raise RetryableStatus(f"gemini returned {result.status_code}")
        return result

    logger.info("analysing %d gap(s) with %s", len(gaps), MODEL)
    response = await with_retry(_attempt, label="gemini analyse")

    if response.status_code != 200:
        raise AnalysisError(
            f"gemini returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()
    usage = payload.get("usageMetadata", {})

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        decisions = json.loads(text)["decisions"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AnalysisError(f"could not parse gemini response: {exc}") from exc

    known = {g["id"] for g in gaps}
    clean = []
    for decision in decisions:
        gap_id = decision.get("gapId")
        if gap_id not in known:
            logger.warning("model returned unknown gap id %r, dropping", gap_id)
            continue
        clean.append(
            {
                "gapId": gap_id,
                "action": "fill" if decision.get("action") == "fill" else "skip",
                "facts": [str(f) for f in (decision.get("facts") or [])],
                "reason": str(decision.get("reason") or ""),
            }
        )

    fills = sum(1 for d in clean if d["action"] == "fill")

    return {
        "decisions": clean,
        "toFill": fills,
        "toSkip": len(clean) - fills,
        # description density from ARCHITECTURE.md's metrics table
        "density": round(fills / len(gaps), 4) if gaps else 0.0,
        "model": MODEL,
        "provider": "google",
        "videoTokens": usage.get("promptTokensDetails"),
        "totalTokens": usage.get("totalTokenCount"),
    }
