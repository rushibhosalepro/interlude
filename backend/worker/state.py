"""Job state, stored in B2 at jobs/{jobId}/state.json.

There is no database. The state file is a summary; the real proof that a stage
finished is that its artifact exists in the bucket. That is what lets the worker
be killed mid-job and pick up where it left off.
"""

import asyncio
from datetime import datetime, timezone

import storage

# live view for the UI. rebuilt from B2 on restart, so losing it costs nothing.
live: dict[str, dict] = {}


def state_key(job_id: str) -> str:
    return f"jobs/{job_id}/state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create(job_id: str, project_id: str, video_id: str, source_key: str) -> dict:
    state = {
        "jobId": job_id,
        "projectId": project_id,
        "videoId": video_id,
        "sourceKey": source_key,
        "status": "queued",
        "stage": None,
        "completedStages": [],
        "error": None,
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    await save(state)
    return state


async def save(state: dict) -> None:
    state["updatedAt"] = _now()
    live[state["jobId"]] = dict(state)
    # boto3 is blocking, so it goes on a thread or the whole server stalls
    await asyncio.to_thread(storage.put_json, state_key(state["jobId"]), state)


async def load(job_id: str) -> dict | None:
    return await asyncio.to_thread(storage.get_json, state_key(job_id))


async def get(job_id: str) -> dict | None:
    """Live copy if we have it, otherwise read it back from B2."""
    if job_id in live:
        return live[job_id]
    return await load(job_id)


async def unfinished_job_ids() -> list[str]:
    """Jobs that were mid-flight when the process died."""
    job_ids = await asyncio.to_thread(storage.list_child_prefixes, "jobs/")
    pending = []

    for job_id in job_ids:
        state = await load(job_id)
        if state and state.get("status") not in {"done", "failed"}:
            live[job_id] = dict(state)
            pending.append(job_id)

    return pending
