from fastapi import APIRouter, HTTPException, Request
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from pathlib import PurePosixPath
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from uuid import uuid4
import asyncio
import json
import logging
import os
import re
import boto3

import worker
from worker import state

logger = logging.getLogger(__name__)

load_dotenv()

application_key_id = os.getenv("BACKBLAZE_APPLICATION_KEY_ID")
application_key = os.getenv("BACKBLAZE_APPLICATION_KEY")
endpoint_url = os.getenv("BACKBLAZE_ENDPOINT_URL")
region = os.getenv("BACKBLAZE_REGION")
media_bucket = os.getenv("BACKBLAZE_MEDIA_BUCKET")
compliance_bucket = os.getenv("BACKBLAZE_COMPLIANCE_BUCKET")

# fail at import rather than handing out broken presigned URLs at request time
_required = {
    "BACKBLAZE_APPLICATION_KEY_ID": application_key_id,
    "BACKBLAZE_APPLICATION_KEY": application_key,
    "BACKBLAZE_ENDPOINT_URL": endpoint_url,
    "BACKBLAZE_REGION": region,
    "BACKBLAZE_MEDIA_BUCKET": media_bucket,
}

_missing = sorted(name for name, value in _required.items() if not value)

if _missing:
    raise RuntimeError(
        f"missing required environment variables: {', '.join(_missing)}. "
        "copy .env.example to .env and fill them in."
    )


client = boto3.client(
    "s3",
    aws_access_key_id=application_key_id,
    aws_secret_access_key=application_key,
    region_name=region,
    endpoint_url=endpoint_url,
)


router = APIRouter()

# video only for now. the extension comes from here, never from the client's
# filename, so the client has no influence over the stored key.
ALLOWED_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
}

EXTENSION_TO_TYPE = {ext: ctype for ctype, ext in ALLOWED_VIDEO_TYPES.items()}

# browsers report an empty type for .mov and .mkv often enough that rejecting
# outright would block real uploads. only these two get the extension fallback,
# an explicit but disallowed type is still a hard reject.
UNKNOWN_CONTENT_TYPES = {"", "application/octet-stream"}

UPLOAD_URL_TTL = 900  # seconds
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB

# projects/{projectId}/source/{videoId}.mp4, per ARCHITECTURE.md. the worker
# derives every other artifact path from the project and video ids, so the
# source has to sit under a project prefix for resume to have anywhere to live.
SOURCE_KEY = re.compile(
    r"^projects/(?P<projectId>[0-9a-f]{32})/source/(?P<videoId>[0-9a-f]{32})\.[a-z0-9]{2,10}$"
)


class PresignRequest(BaseModel):
    filename: str  # kept as metadata to display later, not used to build the key
    content_type: str = ""


class CompleteUploadRequest(BaseModel):
    key: str


def resolve_content_type(raw: str, filename: str) -> str | None:
    """Normalise the client's content type, or None if it isn't an allowed video."""
    # browsers send things like "video/webm;codecs=vp9"
    content_type = raw.split(";")[0].strip().lower()

    if content_type in ALLOWED_VIDEO_TYPES:
        return content_type

    if content_type in UNKNOWN_CONTENT_TYPES:
        return EXTENSION_TO_TYPE.get(PurePosixPath(filename).suffix.lower())

    return None


@router.post("/presigned_url")
def create_presigned_url(payload: PresignRequest):
    content_type = resolve_content_type(payload.content_type, payload.filename)
    if content_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type. Allowed: {', '.join(sorted(ALLOWED_VIDEO_TYPES))}",
        )

    extension = ALLOWED_VIDEO_TYPES[content_type]
    # one project per upload for now. when projects hold several videos, the
    # client sends an existing projectId instead of us minting one here.
    project_id = uuid4().hex
    video_id = uuid4().hex
    key = f"projects/{project_id}/source/{video_id}{extension}"

    try:
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": media_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=UPLOAD_URL_TTL,
        )
    except (BotoCoreError, ClientError):
        logger.exception("could not presign upload for %s", key)
        raise HTTPException(status_code=500, detail="Could not generate upload URL")

    return {
        "presignedUrl": url,
        "key": key,
        "projectId": project_id,
        "videoId": video_id,
        # the PUT must send exactly this, not the browser's own file.type
        "contentType": content_type,
        "filename": payload.filename,
        "expiresIn": UPLOAD_URL_TTL,
    }


@router.post("/uploads/complete")
async def complete_upload(payload: CompleteUploadRequest):
    """Called by the client once the PUT finishes.

    Confirms the object landed, enforces the size cap that a presigned PUT cannot
    enforce itself, then queues the job and returns immediately. The pipeline
    runs behind the response.
    """
    key = payload.key

    # the key is client supplied and we delete on it below, so it has to match
    # the exact shape we hand out rather than being trusted as given
    match = SOURCE_KEY.match(key)
    if match is None:
        raise HTTPException(status_code=400, detail="Unrecognised upload key")

    # this handler is async, so boto3 goes on a thread or it stalls the loop
    # and with it the worker and every other request
    try:
        head = await asyncio.to_thread(
            client.head_object, Bucket=media_bucket, Key=key
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            raise HTTPException(status_code=404, detail="Upload not found")
        logger.exception("head_object failed for %s", key)
        raise HTTPException(status_code=500, detail="Could not verify upload")
    except BotoCoreError:
        logger.exception("head_object failed for %s", key)
        raise HTTPException(status_code=500, detail="Could not verify upload")

    size = head["ContentLength"]
    if size > MAX_UPLOAD_BYTES:
        try:
            await asyncio.to_thread(
                client.delete_object, Bucket=media_bucket, Key=key
            )
        except (BotoCoreError, ClientError):
            logger.exception("could not delete oversized upload %s", key)
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    # hand it to the worker. this returns straight away, the pipeline runs behind it.
    job = await worker.submit(
        project_id=match["projectId"],
        video_id=match["videoId"],
        source_key=key,
    )

    return {
        "key": key,
        "size": size,
        "contentType": head.get("ContentType"),
        "status": "queued",
        "jobId": job["jobId"],
        "projectId": job["projectId"],
        "videoId": job["videoId"],
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """One-shot progress read. The browser uses the SSE stream below instead."""
    job = await worker.get_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """Live progress stream: stage changes, and every fit attempt as it happens."""
    job = await worker.get_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = state.subscribe(job_id)

    async def stream():
        try:
            # current state first, so a browser joining late is not left blank
            yield {"event": "state", "data": json.dumps(job)}

            if job.get("status") in {"done", "failed"}:
                yield {"event": "end", "data": json.dumps({"status": job["status"]})}
                return

            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    # keeps proxies from closing an idle connection
                    yield {"event": "ping", "data": "{}"}
                    continue

                yield {"event": event["type"], "data": json.dumps(event)}

                if event["type"] == "state":
                    status = event["state"].get("status")
                    if status in {"done", "failed"}:
                        yield {"event": "end", "data": json.dumps({"status": status})}
                        return
        finally:
            state.unsubscribe(job_id, queue)

    return EventSourceResponse(stream())
