"""Transcription via Groq's hosted Whisper. Free tier, word level timestamps.

Why hosted instead of local faster-whisper: Smart App Control on Windows blocks
the unsigned ffmpeg DLLs that PyAV ships, and faster-whisper imports PyAV. Groq
accepts the video file directly and does the decoding server side, so nothing
local needs to touch a media codec.

It is also more accurate (large-v3-turbo vs a local base model) and faster.
"""

import asyncio
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"

# groq rejects uploads over this. free tier is 25 MB. beyond it the audio has to
# be extracted and compressed first, which needs ffmpeg.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class TranscriptionError(RuntimeError):
    pass


async def transcribe(video_path: str) -> dict:
    """Word level transcript of a local video file."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise TranscriptionError("GROQ_API_KEY is not set")

    path = Path(video_path)
    size = path.stat().st_size

    if size > MAX_UPLOAD_BYTES:
        raise TranscriptionError(
            f"{path.name} is {size / 1_048_576:.0f} MB, over the "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB limit. Extract and compress the "
            "audio first, which needs ffmpeg."
        )

    logger.info("transcribing %s (%.1f MB) with %s", path.name, size / 1_048_576, MODEL)

    def _post() -> httpx.Response:
        with path.open("rb") as handle:
            return httpx.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (path.name, handle, "application/octet-stream")},
                data={
                    "model": MODEL,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word",
                },
                timeout=300,
            )

    # httpx here is the sync client, so it goes on a thread like every other
    # blocking call, or the event loop stalls for the whole upload
    response = await asyncio.to_thread(_post)

    if response.status_code != 200:
        raise TranscriptionError(
            f"groq returned {response.status_code}: {response.text[:300]}"
        )

    payload = response.json()

    words = [
        {
            "word": w["word"].strip(),
            "start": round(w["start"], 3),
            "end": round(w["end"], 3),
        }
        for w in payload.get("words") or []
    ]

    return {
        "language": payload.get("language"),
        "duration": round(payload.get("duration") or 0.0, 3),
        "text": (payload.get("text") or "").strip(),
        "words": words,
        "model": MODEL,
        "provider": "groq",
    }
