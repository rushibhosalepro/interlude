"""The stages, run in order for one job.

Every stage follows the same shape:

    1. is the artifact already in B2?  -> skip, we did this in a previous run
    2. do the work in a temp folder on local disk
    3. push the result to B2

Local disk is scratch only. Nothing important lives there, which is what makes
killing the process safe.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

import storage
from worker import analyse, fit, gaps, manifest, mux, state, transcribe

logger = logging.getLogger(__name__)


def artifact_key(job: dict, template: str) -> str:
    return f"projects/{job['projectId']}/{template.format(videoId=job['videoId'])}"


async def source_video(job: dict, workdir: Path) -> Path:
    """The source on local disk, downloaded once per job run and reused."""
    local = workdir / "source.mp4"
    if local.exists():
        return local

    logger.info("downloading %s", job["sourceKey"])
    await asyncio.to_thread(
        storage.client.download_file,
        storage.media_bucket,
        job["sourceKey"],
        str(local),
    )
    logger.info("downloaded %.1f MB", local.stat().st_size / 1_048_576)
    return local


async def stage_transcribe(job: dict, workdir: Path) -> None:
    video = await source_video(job, workdir)
    result = await transcribe.transcribe(str(video))
    logger.info(
        "transcribed %.1fs of audio, %d words", result["duration"], len(result["words"])
    )
    await asyncio.to_thread(
        storage.put_json, artifact_key(job, "analysis/{videoId}/transcript.json"), result
    )


async def stage_gaps(job: dict, workdir: Path) -> None:
    transcript = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/transcript.json")
    )
    result = gaps.find_gaps(transcript)
    logger.info(
        "found %d gap(s), %.1fs of describable silence (%.0f%% of the video)",
        result["count"],
        result["totalGapSeconds"],
        result["gapRatio"] * 100,
    )
    await asyncio.to_thread(
        storage.put_json, artifact_key(job, "analysis/{videoId}/gaps.json"), result
    )


async def stage_analyse(job: dict, workdir: Path) -> None:
    """Fill or skip per gap, plus the essential visual facts.

    No keyframe extraction: the video goes to Gemini whole, so the model sees
    motion instead of one still per gap, and nothing local decodes media.
    """
    gap_data = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/gaps.json")
    )
    transcript = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/transcript.json")
    )

    video = await source_video(job, workdir)
    result = await analyse.analyse(str(video), gap_data["gaps"], transcript)

    logger.info(
        "decided %d fill / %d skip (density %.0f%%), %s tokens",
        result.get("toFill", 0),
        result.get("toSkip", 0),
        result.get("density", 0) * 100,
        result.get("totalTokens"),
    )
    await asyncio.to_thread(
        storage.put_json, artifact_key(job, "analysis/{videoId}/decisions.json"), result
    )


async def stage_describe(job: dict, workdir: Path) -> None:
    """Loop 1: write, render, measure, retry until the narration fits the gap."""
    gap_data = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/gaps.json")
    )
    decisions = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/decisions.json")
    )
    transcript = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/transcript.json")
    )

    result = await fit.fit_all(
        job["jobId"], job["projectId"], gap_data["gaps"], decisions["decisions"], transcript
    )

    logger.info(
        "committed %d/%d gap(s) in %d attempt(s), first pass fit %.0f%%",
        result["committed"],
        result["attempted"],
        result["totalAttempts"],
        result["firstPassFitRate"] * 100,
    )
    await asyncio.to_thread(
        storage.put_json, artifact_key(job, "analysis/{videoId}/descriptions.json"), result
    )


async def stage_mux(job: dict, workdir: Path) -> None:
    """Mix narration into the original audio and write the VTT alongside it."""
    descriptions = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/descriptions.json")
    )
    gap_data = await asyncio.to_thread(
        storage.get_json, artifact_key(job, "analysis/{videoId}/gaps.json")
    )
    gaps_by_id = {g["id"]: g for g in gap_data["gaps"]}
    committed = [r for r in descriptions["results"] if r["status"] == "committed"]

    video = await source_video(job, workdir)
    audio, seconds = await mux.mux(
        job["projectId"], str(video), committed, gaps_by_id, workdir
    )

    await asyncio.to_thread(
        storage.put_bytes,
        artifact_key(job, "final/{videoId}/described-audio.m4a"),
        audio,
        "audio/mp4",
    )
    await asyncio.to_thread(
        storage.put_bytes,
        artifact_key(job, "final/{videoId}/descriptions.vtt"),
        mux.build_vtt(committed, gaps_by_id).encode(),
        "text/vtt",
    )

    logger.info(
        "muxed %.1fs of described audio, %.1f MB, %d description(s)",
        seconds,
        len(audio) / 1_048_576,
        len(committed),
    )


async def stage_publish(job: dict, workdir: Path) -> None:
    """Write the Genblaze manifest to the Object Lock bucket.

    The receipt lives in the media bucket so the resume check can see it; the
    manifest itself is locked in the compliance bucket where it cannot be edited.
    """
    receipt = await manifest.publish(job)
    await asyncio.to_thread(
        storage.put_json, artifact_key(job, "final/{videoId}/manifest.json"), receipt
    )


# in order. coverage (loop 2) still to come.
STAGES = [
    ("transcribe", "analysis/{videoId}/transcript.json", stage_transcribe),
    ("gaps", "analysis/{videoId}/gaps.json", stage_gaps),
    ("analyse", "analysis/{videoId}/decisions.json", stage_analyse),
    ("describe", "analysis/{videoId}/descriptions.json", stage_describe),
    ("mux", "final/{videoId}/described-audio.m4a", stage_mux),
    ("publish", "final/{videoId}/manifest.json", stage_publish),
]


async def run(job_id: str) -> None:
    job = await state.load(job_id)
    if job is None:
        logger.warning("job %s has no state file, skipping", job_id)
        return

    job["status"] = "running"
    completed = list(job.get("completedStages") or [])

    # one temp folder per job, deleted automatically when the block exits
    with tempfile.TemporaryDirectory(prefix=f"interlude-{job_id[:8]}-") as tmp:
        workdir = Path(tmp)

        for name, template, run_stage in STAGES:
            key = artifact_key(job, template)

            # the resume check
            if await asyncio.to_thread(storage.object_exists, key):
                logger.info("job %s: %s already done, skipping", job_id, name)
                if name not in completed:
                    completed.append(name)
                continue

            job["stage"] = name
            job["completedStages"] = completed
            await state.save(job)

            logger.info("job %s: running %s", job_id, name)
            await run_stage(job, workdir)

            completed.append(name)

    job["status"] = "done"
    job["stage"] = None
    job["completedStages"] = completed
    await state.save(job)
    logger.info("job %s: finished", job_id)
