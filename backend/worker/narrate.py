"""Text to speech via ElevenLabs, with exact duration measurement.

Asks for raw PCM rather than mp3 for one reason: duration is then arithmetic on
the byte count, with no decoder involved. Smart App Control blocks the unsigned
ffmpeg DLLs that PyAV ships, so nothing local can decode an mp3.

The PCM is wrapped in a WAV header using the stdlib `wave` module, so what lands
in B2 is a normal playable file with no dependencies.
"""

import asyncio
import io
import json
import logging
import os
import wave

import httpx

logger = logging.getLogger(__name__)

# free tier premade voice. voices from the ElevenLabs voice *library* return 402
# on free accounts, which is the trap: the id looks valid and the call fails.
DEFAULT_VOICE = "pNInz6obpgDQGcFmaJgB"  # Adam

SAMPLE_RATE = 24000  # pcm_44100 is Pro tier only
SAMPLE_WIDTH = 2  # 16 bit signed
CHANNELS = 1

MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"


class NarrationError(RuntimeError):
    pass


def _to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    return buffer.getvalue()


def _duration(pcm: bytes) -> float:
    """Exact, because raw PCM has a fixed bytes-per-second."""
    return len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)


async def narrate(text: str, speed: float = 1.0) -> tuple[bytes, float]:
    """Returns (wav bytes, duration in seconds).

    speed above 1.0 compresses the delivery, which is the last resort in the fit
    loop before dropping content. ElevenLabs accepts 0.7 to 1.2.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise NarrationError("ELEVENLABS_API_KEY is not set")

    voice = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE

    settings = {"stability": 0.5, "similarity_boost": 0.75}
    if speed != 1.0:
        settings["speed"] = round(speed, 2)

    def _post() -> httpx.Response:
        return httpx.post(
            f"{ENDPOINT}/{voice}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            params={"output_format": f"pcm_{SAMPLE_RATE}"},
            json={"text": text, "model_id": MODEL, "voice_settings": settings},
            timeout=120,
        )

    response = await asyncio.to_thread(_post)

    if response.status_code != 200:
        detail = response.text[:300]
        try:
            detail = json.loads(response.text)["detail"].get("message", detail)
        except Exception:
            pass
        if response.status_code == 402 and "library voices" in detail:
            detail += (
                f" -- set ELEVENLABS_VOICE_ID to a premade voice such as "
                f"{DEFAULT_VOICE} (Adam), or leave it blank."
            )
        raise NarrationError(f"elevenlabs returned {response.status_code}: {detail}")

    pcm = response.content
    return _to_wav(pcm), _duration(pcm)
