"""Pre-seeded clips a judge can run without uploading anything.

ARCHITECTURE.md calls this non-negotiable: requiring judges to supply input is
what sank a previous submission. One click queues a real job through the same
pipeline as an upload, so nothing about the demo is special-cased.

Clips live at samples/{sampleId}.mp4 in the media bucket. Seed them with
scripts/seed_samples.py.
"""

import asyncio
import logging
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException

import storage
import worker

logger = logging.getLogger(__name__)

router = APIRouter()

SAMPLE_PREFIX = "samples/"
SAMPLE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")
PREVIEW_URL_TTL = 3600


def _list_samples() -> list[dict]:
    resp = storage.client.list_objects_v2(
        Bucket=storage.media_bucket, Prefix=SAMPLE_PREFIX
    )
    samples = []
    for entry in resp.get("Contents", []):
        name = entry["Key"][len(SAMPLE_PREFIX) :]
        if not name.endswith(".mp4"):
            continue
        sample_id = name[: -len(".mp4")]
        head = storage.client.head_object(Bucket=storage.media_bucket, Key=entry["Key"])
        meta = head.get("Metadata") or {}
        samples.append(
            {
                "sampleId": sample_id,
                "title": meta.get("title") or sample_id.replace("-", " "),
                "seconds": float(meta["seconds"]) if meta.get("seconds") else None,
                "sizeBytes": entry["Size"],
                "previewUrl": storage.client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": storage.media_bucket, "Key": entry["Key"]},
                    ExpiresIn=PREVIEW_URL_TTL,
                ),
            }
        )
    return samples


@router.get("/samples")
async def list_samples():
    """Clips available to run with one click."""
    samples = await asyncio.to_thread(_list_samples)
    return {"samples": samples, "count": len(samples)}


@router.post("/samples/{sample_id}/run")
async def run_sample(sample_id: str):
    """Copy a sample into a fresh project and queue it, same as an upload would."""
    if not SAMPLE_ID.match(sample_id):
        raise HTTPException(status_code=400, detail="Invalid sample id")

    source_key = f"{SAMPLE_PREFIX}{sample_id}.mp4"
    if not await asyncio.to_thread(storage.object_exists, source_key):
        raise HTTPException(status_code=404, detail="Sample not found")

    project_id = uuid4().hex
    video_id = uuid4().hex
    key = f"projects/{project_id}/source/{video_id}.mp4"

    # server side copy, so nothing moves through this process
    await asyncio.to_thread(
        storage.client.copy_object,
        Bucket=storage.media_bucket,
        CopySource={"Bucket": storage.media_bucket, "Key": source_key},
        Key=key,
    )

    job = await worker.submit(
        project_id=project_id, video_id=video_id, source_key=key
    )
    logger.info("queued sample %s as job %s", sample_id, job["jobId"])

    return {
        "sampleId": sample_id,
        "jobId": job["jobId"],
        "projectId": project_id,
        "videoId": video_id,
        "status": "queued",
    }
