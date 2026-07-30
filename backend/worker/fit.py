"""Loop 1 from ARCHITECTURE.md: make the narration fit the silence.

Hard and deterministic. No judge model. If the gap is 3.2s and the render is
4.1s, it failed, and we try again shorter. Every attempt is kept in B2 so the UI
can show the failed ones struck through, which is the visible part of the demo.

Order of escalation:
  1. rewrite shorter, up to MAX_ATTEMPTS times
  2. speed the delivery up, to MAX_SPEED
  3. give up on that gap and leave it silent
"""

import asyncio
import logging

import storage
from worker import narrate, state, write

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
MAX_SPEED = 1.15  # beyond this it sounds rushed and hurts comprehension


def _dialogue_around(transcript: dict, gap: dict, window: float = 8.0) -> tuple[str, str]:
    words = transcript.get("words") or []
    before = [w["word"] for w in words if gap["start"] - window <= w["end"] <= gap["start"]]
    after = [w["word"] for w in words if gap["end"] <= w["start"] <= gap["end"] + window]
    return " ".join(before), " ".join(after)


async def _store_attempt(
    project_id: str, gap_id: str, number: int, record: dict, audio: bytes
) -> None:
    base = f"projects/{project_id}/attempts/{gap_id}/{number}"
    await asyncio.to_thread(storage.put_json, f"{base}/text.json", record)
    await asyncio.to_thread(storage.put_bytes, f"{base}/audio.wav", audio, "audio/wav")


async def fit_gap(
    job_id: str, project_id: str, gap: dict, facts: list[str], transcript: dict
) -> dict:
    """Write, render, measure, retry until it fits. Returns the outcome for one gap."""
    target = gap["duration"]
    before, after = _dialogue_around(transcript, gap)

    budget = gap["wordBudget"]
    attempts: list[dict] = []
    previous_text: str | None = None
    previous_actual: float | None = None

    for number in range(1, MAX_ATTEMPTS + 1):
        text = await write.write_description(
            facts=facts,
            budget_words=budget,
            seconds=target,
            before=before,
            after=after,
            previous=previous_text,
            actual=previous_actual,
        )
        audio, actual = await narrate.narrate(text)
        fits = actual <= target

        record = {
            "attempt": number,
            "text": text,
            "words": len(text.split()),
            "budgetWords": budget,
            "durationSeconds": round(actual, 3),
            "targetSeconds": round(target, 3),
            "speed": 1.0,
            "fits": fits,
        }
        attempts.append(record)
        await _store_attempt(project_id, gap["id"], number, record, audio)
        state.publish(job_id, {"type": "attempt", "gapId": gap["id"], **record})

        logger.info(
            "  %s attempt %d: %d words, %.2fs vs %.2fs target -> %s",
            gap["id"],
            number,
            record["words"],
            actual,
            target,
            "FITS" if fits else "too long",
        )

        if fits:
            return {
                "gapId": gap["id"],
                "status": "committed",
                "committedAttempt": number,
                "text": text,
                "durationSeconds": round(actual, 3),
                "speed": 1.0,
                "attempts": attempts,
                "firstPass": number == 1,
            }

        # scale the budget by how much we overran, so the next try aims correctly
        budget = max(2, int(budget * (target / actual)))
        previous_text, previous_actual = text, actual

    # rewriting did not get there. try saying the shortest attempt faster.
    shortest = min(attempts, key=lambda a: a["durationSeconds"])
    for speed in (1.08, MAX_SPEED):
        audio, actual = await narrate.narrate(shortest["text"], speed=speed)
        number = len(attempts) + 1
        fits = actual <= target

        record = {
            "attempt": number,
            "text": shortest["text"],
            "words": shortest["words"],
            "budgetWords": budget,
            "durationSeconds": round(actual, 3),
            "targetSeconds": round(target, 3),
            "speed": speed,
            "fits": fits,
        }
        attempts.append(record)
        await _store_attempt(project_id, gap["id"], number, record, audio)
        state.publish(job_id, {"type": "attempt", "gapId": gap["id"], **record})

        logger.info(
            "  %s attempt %d at %.2fx: %.2fs vs %.2fs -> %s",
            gap["id"],
            number,
            speed,
            actual,
            target,
            "FITS" if fits else "still too long",
        )

        if fits:
            return {
                "gapId": gap["id"],
                "status": "committed",
                "committedAttempt": number,
                "text": shortest["text"],
                "durationSeconds": round(actual, 3),
                "speed": speed,
                "attempts": attempts,
                "firstPass": False,
            }

    # leaving it silent beats talking over the dialogue
    logger.warning("  %s: no attempt fit, leaving silent", gap["id"])
    return {
        "gapId": gap["id"],
        "status": "abandoned",
        "committedAttempt": None,
        "text": None,
        "attempts": attempts,
        "firstPass": False,
    }


async def fit_all(
    job_id: str, project_id: str, gaps: list[dict], decisions: list[dict], transcript: dict
) -> dict:
    by_id = {g["id"]: g for g in gaps}
    facts_by_id = {
        d["gapId"]: d["facts"] for d in decisions if d.get("action") == "fill"
    }

    results = []
    for gap_id, facts in facts_by_id.items():
        gap = by_id.get(gap_id)
        if gap is None or not facts:
            continue
        logger.info("fitting %s (%.2fs available)", gap_id, gap["duration"])
        state.publish(
            job_id,
            {"type": "gap-start", "gapId": gap_id, "available": gap["duration"], "facts": facts},
        )
        result = await fit_gap(job_id, project_id, gap, facts, transcript)
        state.publish(job_id, {"type": "gap-done", "gapId": gap_id, **{k: v for k, v in result.items() if k != "attempts"}})
        results.append(result)

    committed = [r for r in results if r["status"] == "committed"]
    first_pass = [r for r in committed if r["firstPass"]]

    return {
        "results": results,
        "attempted": len(results),
        "committed": len(committed),
        "abandoned": len(results) - len(committed),
        # the fit rate metric from ARCHITECTURE.md, first pass vs final
        "firstPassFitRate": round(len(first_pass) / len(results), 4) if results else 0.0,
        "finalFitRate": round(len(committed) / len(results), 4) if results else 0.0,
        "totalAttempts": sum(len(r["attempts"]) for r in results),
    }
