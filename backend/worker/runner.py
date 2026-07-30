"""The queue and the loop that drains it. One worker, one job at a time."""

import asyncio
import logging
from uuid import uuid4

from worker import pipeline, state

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[str] = asyncio.Queue()
_task: asyncio.Task | None = None

# job ids already queued or running. without this, the resume scan re-queues
# jobs that submit() just added, and the pipeline runs twice.
_inflight: set[str] = set()


async def _enqueue(job_id: str) -> bool:
    if job_id in _inflight:
        return False
    _inflight.add(job_id)
    await _queue.put(job_id)
    return True


async def submit(project_id: str, video_id: str, source_key: str) -> dict:
    """Record the job and put it on the queue. Returns immediately."""
    job_id = uuid4().hex
    job = await state.create(job_id, project_id, video_id, source_key)
    await _enqueue(job_id)
    logger.info("job %s queued for %s", job_id, source_key)
    return job


async def _loop() -> None:
    # anything that was mid-flight when the process died goes back on the queue
    for job_id in await state.unfinished_job_ids():
        if await _enqueue(job_id):
            logger.info("resumed job %s from B2", job_id)

    while True:
        job_id = await _queue.get()
        try:
            await pipeline.run(job_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("job %s failed", job_id)
            job = await state.load(job_id)
            if job:
                job["status"] = "failed"
                job["error"] = str(exc)
                await state.save(job)
        finally:
            _inflight.discard(job_id)
            _queue.task_done()


def start() -> None:
    """Called once when the API boots."""
    global _task
    _task = asyncio.create_task(_loop())
    logger.info("worker started")


async def stop() -> None:
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    logger.info("worker stopped")
