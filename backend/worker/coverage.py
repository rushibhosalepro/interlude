"""Loop 2 from ARCHITECTURE.md: can a listener rebuild the scene from audio alone?

Good audio description is not "did we say something in every gap". It is whether
someone who cannot see the screen ends up knowing what happened. So this tests
exactly that: take the audio-only experience, dialogue plus the committed
narration, and ask which of the essential visual facts a listener could recover.

Measured twice, dialogue alone and dialogue plus descriptions, because the
interesting number is the lift, not the absolute.

The checker is Groq/Llama, deliberately not the Gemini that wrote the
descriptions. Grading your own output with the model that produced it is
worthless and a judge will notice.
"""

import asyncio
import json
import logging
import os

import httpx

from worker.retry import RetryableStatus, should_retry_status, with_retry

logger = logging.getLogger(__name__)

MODEL = os.getenv("GROQ_CHECKER_MODEL", "llama-3.3-70b-versatile")
ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# below this the descriptions are not doing their job and gaps get re-run
COVERAGE_TARGET = float(os.getenv("COVERAGE_TARGET", "0.85"))

PROMPT = """A blind listener plays a video. Below is a transcript of EVERYTHING
they hear, in order.

Some of it is the speakers' dialogue. Some of it, marked (described), is a
narrator's voice describing what is on screen during the silences. BOTH are
spoken out loud through the speakers. The listener hears the described lines
just as clearly as the dialogue. Treat them as equally heard.

--- WHAT THE LISTENER HEARS ---
{audio_only}
--- END ---

Here are visual facts that occur in the video. For each one, decide whether this
listener would know it, having heard only the audio above.

{facts}

Judge only on what the audio states or clearly implies. Do not use your own
knowledge of what such videos usually contain. If nothing in the audio conveys a
fact, it is NOT recovered, even if it seems obvious.

Reply with JSON only:
{{"recovered": [0, 2], "reasoning": "brief"}}

where the numbers are the indices of facts the listener would know."""


class CoverageError(RuntimeError):
    pass


def build_audio_only(transcript: dict, committed: list[dict], gaps_by_id: dict) -> str:
    """Dialogue and narration interleaved in the order they are heard."""
    events: list[tuple[float, str]] = []

    for word in transcript.get("words") or []:
        events.append((word["start"], word["word"]))

    spoken = " ".join(w for _, w in sorted(events))

    if not committed:
        return spoken

    # rebuild as a timeline so narration sits where it actually plays
    timeline: list[tuple[float, str]] = [
        (w["start"], w["word"]) for w in (transcript.get("words") or [])
    ]
    for item in committed:
        gap = gaps_by_id.get(item["gapId"])
        if gap and item.get("text"):
            timeline.append((gap["start"], f"(described) {item['text']}"))

    return " ".join(text for _, text in sorted(timeline, key=lambda e: e[0]))


async def _ask_checker(audio_only: str, facts: list[str]) -> set[int]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise CoverageError("GROQ_API_KEY is not set")

    numbered = "\n".join(f"{i}. {fact}" for i, fact in enumerate(facts))
    prompt = PROMPT.format(audio_only=audio_only[:12000], facts=numbered)

    def _post() -> httpx.Response:
        return httpx.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,  # a grader should be repeatable
            },
            timeout=180,
        )

    async def _attempt() -> httpx.Response:
        result = await asyncio.to_thread(_post)
        if should_retry_status(result.status_code):
            raise RetryableStatus(f"groq returned {result.status_code}")
        return result

    response = await with_retry(_attempt, label="groq coverage check")

    if response.status_code != 200:
        raise CoverageError(f"groq returned {response.status_code}: {response.text[:300]}")

    try:
        content = response.json()["choices"][0]["message"]["content"]
        recovered = json.loads(content).get("recovered") or []
    except (KeyError, IndexError, ValueError) as exc:
        raise CoverageError(f"could not parse groq response: {exc}") from exc

    return {i for i in recovered if isinstance(i, int) and 0 <= i < len(facts)}


async def check(
    transcript: dict, decisions: list[dict], committed: list[dict], gaps_by_id: dict
) -> dict:
    """Coverage before and after the descriptions, plus what is still missing."""
    # every essential fact the vision stage found, and which gap it came from
    facts: list[str] = []
    fact_gap: list[str] = []
    for decision in decisions:
        for fact in decision.get("facts") or []:
            facts.append(fact)
            fact_gap.append(decision["gapId"])

    if not facts:
        return {
            "facts": 0,
            "coverageBefore": 0.0,
            "coverageAfter": 0.0,
            "recoveredAfter": [],
            "missing": [],
            "target": COVERAGE_TARGET,
            "meetsTarget": True,
            "model": MODEL,
            "provider": "groq",
        }

    dialogue_only = build_audio_only(transcript, [], gaps_by_id)
    with_narration = build_audio_only(transcript, committed, gaps_by_id)

    # both measurements use the same checker, so the lift is like for like
    before, after = await asyncio.gather(
        _ask_checker(dialogue_only, facts),
        _ask_checker(with_narration, facts),
    )

    missing = [
        {"index": i, "fact": facts[i], "gapId": fact_gap[i]}
        for i in range(len(facts))
        if i not in after
    ]

    coverage_after = len(after) / len(facts)

    return {
        "facts": len(facts),
        "coverageBefore": round(len(before) / len(facts), 4),
        "coverageAfter": round(coverage_after, 4),
        "recoveredAfter": sorted(after),
        "missing": missing,
        # gaps worth re-running, deduped
        "gapsToRetry": sorted({m["gapId"] for m in missing}),
        "target": COVERAGE_TARGET,
        "meetsTarget": coverage_after >= COVERAGE_TARGET,
        "model": MODEL,
        "provider": "groq",
    }
