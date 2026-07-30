"""Provenance record for one run, written to the Object Lock bucket.

Every description a blind viewer hears was produced by a model. If one turns out
to be wrong, somebody has to be able to ask where it came from. This is the
answer: which provider and model, from which prompt and parameters, when, and a
hash of what came out.

The manifest is Genblaze's own document, not a hand-rolled audit log. It carries
a canonical hash, so altering the record later is detectable.

It goes to the compliance bucket with Object Lock set, because a compliance
record that can be edited is worthless.
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

from genblaze import (
    Manifest,
    ObjectLockConfig,
    PromptVisibility,
    RunBuilder,
    RunStatus,
    StepBuilder,
    StepStatus,
    StepType,
)

import storage
from worker import analyse, narrate, transcribe, write

logger = logging.getLogger(__name__)

# how long the record is locked against modification, including by us
RETENTION_DAYS = int(os.getenv("COMPLIANCE_RETENTION_DAYS", "30"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset(key: str, media_type: str, data: bytes) -> dict:
    """Kwargs for StepBuilder.asset(). The sha256 is what makes the record
    tamper evident: change the audio later and it no longer matches."""
    return {
        "url": f"s3://{storage.media_bucket}/{key}",
        "media_type": media_type,
        "asset_id": key,
        "sha256": _sha256(data),
        "size_bytes": len(data),
    }


def build_run(
    job: dict,
    transcript: dict,
    decisions: dict,
    descriptions: dict,
    final_assets: list[dict],
):
    """One Run, one step per real provider call, in pipeline order."""
    builder = (
        RunBuilder("interlude-describe")
        .run_id(job["jobId"])
        .project(job["projectId"])
        .status(RunStatus.COMPLETED)
        .meta(
            **{
                "videoId": job["videoId"],
                "sourceKey": job["sourceKey"],
                # the honest numbers from ARCHITECTURE.md's metrics table
                "gapsFound": str(decisions.get("toFill", 0) + decisions.get("toSkip", 0)),
                "descriptionDensity": str(decisions.get("density", 0)),
                "firstPassFitRate": str(descriptions.get("firstPassFitRate", 0)),
                "finalFitRate": str(descriptions.get("finalFitRate", 0)),
                "totalAttempts": str(descriptions.get("totalAttempts", 0)),
            }
        )
    )

    builder.add_step(
        StepBuilder("groq", transcript.get("model", transcribe.MODEL))
        .step_type(StepType.CUSTOM)
        .modality("audio")
        .status(StepStatus.SUCCEEDED)
        .params(**{"response_format": "verbose_json", "granularity": "word"})
        .meta(**{"words": str(len(transcript.get("words") or [])),
               "language": str(transcript.get("language"))})
        .build()
    )

    builder.add_step(
        StepBuilder("google", decisions.get("model", analyse.MODEL))
        .step_type(StepType.CUSTOM)
        .modality("video")
        .status(StepStatus.SUCCEEDED)
        .prompt(analyse.PROMPT)
        # prompts can contain customer content, so the text is recorded but not exposed
        .visibility(PromptVisibility.PRIVATE)
        .params(**{"temperature": 0.2, "responseMimeType": "application/json"})
        .meta(**{"toFill": str(decisions.get("toFill", 0)),
               "toSkip": str(decisions.get("toSkip", 0))})
        .build()
    )

    # one step per committed description, so a wrong line traces to its own call
    for result in descriptions.get("results", []):
        if result["status"] != "committed":
            continue
        builder.add_step(
            StepBuilder("google", write.MODEL)
            .step_type(StepType.GENERATE)
            .modality("text")
            .status(StepStatus.SUCCEEDED)
            .prompt(write.PROMPT)
            .visibility(PromptVisibility.PRIVATE)
            .params(**{"temperature": 0.4, "attempts": len(result["attempts"])})
            .meta(**{"gapId": result["gapId"], "text": result["text"] or "",
                   "committedAttempt": str(result["committedAttempt"])})
            .build()
        )
        builder.add_step(
            StepBuilder("elevenlabs", narrate.MODEL)
            .step_type(StepType.GENERATE)
            .modality("audio")
            .status(StepStatus.SUCCEEDED)
            .params(**{"output_format": f"pcm_{narrate.SAMPLE_RATE}",
                     "speed": result.get("speed", 1.0)})
            .meta(**{"gapId": result["gapId"],
                   "durationSeconds": str(result["durationSeconds"])})
            .build()
        )

    mix = (
        StepBuilder("ffmpeg", "ffmpeg")
        .step_type(StepType.MIX)
        .modality("audio")
        .status(StepStatus.SUCCEEDED)
        .params(**{"duck": 0.25, "codec": "aac"})
    )
    for asset in final_assets:
        mix = mix.asset(**asset)
    builder.add_step(mix.build())

    return builder.build()


async def publish(job: dict) -> dict:
    """Build the manifest, lock it into the compliance bucket, verify it."""
    if not storage.compliance_bucket:
        raise RuntimeError("BACKBLAZE_COMPLIANCE_BUCKET is not set")

    base = f"projects/{job['projectId']}"
    video_id = job["videoId"]

    transcript = await asyncio.to_thread(
        storage.get_json, f"{base}/analysis/{video_id}/transcript.json"
    )
    decisions = await asyncio.to_thread(
        storage.get_json, f"{base}/analysis/{video_id}/decisions.json"
    )
    descriptions = await asyncio.to_thread(
        storage.get_json, f"{base}/analysis/{video_id}/descriptions.json"
    )

    # hash what was actually produced, read back from storage
    final_assets = []
    for name, media_type in (
        ("described-audio.m4a", "audio/mp4"),
        ("descriptions.vtt", "text/vtt"),
    ):
        key = f"{base}/final/{video_id}/{name}"
        body = await asyncio.to_thread(
            lambda k=key: storage.client.get_object(
                Bucket=storage.media_bucket, Key=k
            )["Body"].read()
        )
        final_assets.append(_asset(key, media_type, body))

    run = build_run(job, transcript, decisions, descriptions, final_assets)
    manifest = Manifest.from_run(run)

    stamped = datetime.now(timezone.utc)
    key = f"compliance/{job['projectId']}/{video_id}/{stamped.isoformat()}.json"

    lock = ObjectLockConfig(retain_until=stamped + timedelta(days=RETENTION_DAYS))

    await asyncio.to_thread(
        lambda: storage.client.put_object(
            Bucket=storage.compliance_bucket,
            Key=key,
            Body=manifest.model_dump_json(indent=2).encode(),
            ContentType="application/json",
            **lock.to_extra_args(),
        )
    )

    logger.info(
        "manifest %s locked until %s (%d steps, hash %s)",
        key,
        lock.retain_until.date(),
        len(run.steps),
        manifest.canonical_hash[:16],
    )

    return {
        "manifestKey": key,
        "bucket": storage.compliance_bucket,
        "canonicalHash": manifest.canonical_hash,
        "steps": len(run.steps),
        "retainUntil": lock.retain_until.isoformat(),
        "runId": run.run_id,
    }
