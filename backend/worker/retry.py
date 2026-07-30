"""Retry transient network failures.

A single flaky SSL handshake killed a whole job during testing. Provider calls go
over the internet, so treat a dropped connection or a 429 as normal and try
again rather than failing the job.

Deliberately does NOT retry 4xx other than 429: a bad API key or an unsupported
voice will fail identically every time, and retrying just wastes the demo clock.
"""

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE = (
    httpx.TransportError,  # covers connect, read, write and protocol errors
    httpx.RemoteProtocolError,
)


class RetryableStatus(RuntimeError):
    """Raised by callers for a status code worth trying again, e.g. 429 or 5xx."""


def should_retry_status(status: int) -> bool:
    return status == 429 or status >= 500


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 1.5,
    label: str = "call",
) -> T:
    last: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except (*RETRYABLE, RetryableStatus) as exc:
            last = exc
            if attempt == attempts:
                break
            # exponential backoff with jitter, so parallel retries do not sync up
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "%s failed (%s), retrying in %.1fs [%d/%d]",
                label,
                type(exc).__name__,
                delay,
                attempt,
                attempts,
            )
            await asyncio.sleep(delay)

    raise RuntimeError(f"{label} failed after {attempts} attempts: {last}") from last
