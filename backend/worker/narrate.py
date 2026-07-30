"""Narration, orchestrated through a Genblaze Pipeline.

The TTS step is a real generation step, so it runs through the SDK:
ElevenLabsTTSProvider inside a Pipeline, with an ObjectStorageSink writing
renders to B2 under a content-addressable key. Identical description text hashes
to the same key, which is where the cache hit rate comes from.

Two things are deliberate and worth knowing:

* PCM, not mp3. Duration is then exact arithmetic on the byte count, with no
  decoder involved. The fit loop's pass/fail depends on that measurement, so it
  stays independent of anything the SDK reports.

* The speed escalation bypasses the SDK. genblaze-elevenlabs builds
  voice_settings from stability, similarity_boost and style only; `speed` is
  never forwarded. Routing it through the adapter would render at normal speed
  while looking like it worked, quietly breaking the last rung of the fit loop's
  escalation ladder. So attempts at speed 1.0 go through Genblaze and the
  compressed retries go direct, rather than weakening the loop.
"""

import asyncio
import io
import json
import logging
import os
import tempfile
import wave
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from worker.retry import RetryableStatus, should_retry_status, with_retry

logger = logging.getLogger(__name__)

# free tier premade voice. voices from the ElevenLabs voice *library* return 402
# on free accounts, which is the trap: the id looks valid and the call fails.
DEFAULT_VOICE = "pNInz6obpgDQGcFmaJgB"  # Adam

SAMPLE_RATE = 24000  # pcm_44100 is Pro tier only
SAMPLE_WIDTH = 2  # 16 bit signed
CHANNELS = 1
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"

MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech"

# SDK-written assets live under their own prefix so they cannot collide with the
# hand-managed projects/{projectId}/... layout
SDK_PREFIX = os.getenv("GENBLAZE_ASSET_PREFIX", "genblaze")


class NarrationError(RuntimeError):
    pass


class _CountingCache:
    """StepCache that records hits and misses, which the SDK does not expose."""

    def __init__(self, cache_dir: str):
        from genblaze import StepCache

        self._inner = StepCache(cache_dir)
        self.hits = 0
        self.misses = 0

    def get(self, *args, **kwargs):
        found = self._inner.get(*args, **kwargs)
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def put(self, *args, **kwargs):
        return self._inner.put(*args, **kwargs)

    def clear(self, *args, **kwargs):
        return self._inner.clear(*args, **kwargs)

    @property
    def corruption_count(self):
        return self._inner.corruption_count


_provider = None
_sink = None
_cache: _CountingCache | None = None
_render_dir: Path | None = None

# per-process totals, surfaced in job state
stats = {"sdkRenders": 0, "directRenders": 0, "estimatedCostUsd": 0.0}


def _setup():
    """Build the provider, sink and cache once, lazily."""
    global _provider, _sink, _cache, _render_dir
    if _provider is not None:
        return

    from genblaze import KeyStrategy, ObjectStorageSink
    from genblaze_elevenlabs import ElevenLabsTTSProvider
    from genblaze_s3 import S3StorageBackend

    import storage as store

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise NarrationError("ELEVENLABS_API_KEY is not set")

    _render_dir = Path(tempfile.mkdtemp(prefix="interlude-tts-"))
    _provider = ElevenLabsTTSProvider(api_key=api_key, output_dir=_render_dir)

    _sink = ObjectStorageSink(
        S3StorageBackend.for_backblaze(store.media_bucket),
        prefix=SDK_PREFIX,
        # identical text renders to an identical key, which is the cache story
        key_strategy=KeyStrategy.CONTENT_ADDRESSABLE,
    )

    _cache = _CountingCache(str(_render_dir / "cache"))
    logger.info("genblaze tts pipeline ready, assets under %s/", SDK_PREFIX)


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


def _local_path(url: str) -> Path:
    """file:///C:/... back to a real path, on any platform."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path)


def _rendered_file(step) -> Path | None:
    """The file the provider wrote, named after the step id."""
    if _render_dir is None:
        return None
    for candidate in _render_dir.glob(f"{step.step_id}.*"):
        if candidate.is_file():
            return candidate
    return None


async def _fetch_asset(url: str) -> bytes:
    """Read the render back out of B2 when the local copy is gone."""
    import storage as store

    key = url.split(f"{store.media_bucket}/", 1)[-1].lstrip("/")

    def _get() -> bytes:
        return store.client.get_object(Bucket=store.media_bucket, Key=key)["Body"].read()

    return await asyncio.to_thread(_get)


async def _narrate_via_genblaze(text: str, voice: str) -> bytes:
    """One Pipeline, one generation step. Returns the raw PCM bytes."""
    from genblaze import Modality, Pipeline, PromptVisibility, StepType

    _setup()

    pipeline = (
        Pipeline("interlude-narrate", project_id=os.getenv("GENBLAZE_PROJECT", "interlude"))
        .cache(_cache)
        .step(
            _provider,
            model=MODEL,
            prompt=text,
            modality=Modality.AUDIO,
            step_type=StepType.GENERATE,
            # the narration text is customer-derived, so record it privately
            prompt_visibility=PromptVisibility.PRIVATE,
            params={
                "voice_id": voice,
                "output_format": OUTPUT_FORMAT,
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        )
    )

    result = await pipeline.arun(sink=_sink)

    # succeeded_steps/error_summary are methods on PipelineResult, not properties
    succeeded = result.succeeded_steps()
    if not succeeded:
        raise NarrationError(f"genblaze tts step failed: {result.error_summary()}")

    step = succeeded[0]
    assets = list(step.assets or [])
    if not assets:
        raise NarrationError("genblaze tts step returned no asset")

    # The sink rewrites asset.url to the B2 key once uploaded, so the local file
    # url the provider produced is gone by the time we see the result. The
    # provider writes to output_dir/{step_id}{ext}, so resolve it from the step.
    # This matters: the fit loop must measure the bytes it actually got, not a
    # duration reported back to it.
    path = _rendered_file(step)
    if path is None:
        # last resort, pull the bytes back from where the sink put them
        logger.warning("local render for %s missing, fetching from storage", step.step_id)
        return await _fetch_asset(assets[0].url)

    cost = pipeline.estimated_cost()
    if cost is not None:
        stats["estimatedCostUsd"] = round(stats["estimatedCostUsd"] + float(cost), 6)
    stats["sdkRenders"] += 1

    return path.read_bytes()


async def _narrate_direct(text: str, voice: str, speed: float) -> bytes:
    """Speed-adjusted render. Direct because the adapter drops `speed`."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise NarrationError("ELEVENLABS_API_KEY is not set")

    settings = {"stability": 0.5, "similarity_boost": 0.75, "speed": round(speed, 2)}

    def _post() -> httpx.Response:
        return httpx.post(
            f"{ENDPOINT}/{voice}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            params={"output_format": OUTPUT_FORMAT},
            json={"text": text, "model_id": MODEL, "voice_settings": settings},
            timeout=120,
        )

    async def _attempt() -> httpx.Response:
        result = await asyncio.to_thread(_post)
        if should_retry_status(result.status_code):
            raise RetryableStatus(f"elevenlabs returned {result.status_code}")
        return result

    response = await with_retry(_attempt, label="elevenlabs narrate")

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

    stats["directRenders"] += 1
    return response.content


async def narrate(text: str, speed: float = 1.0) -> tuple[bytes, float]:
    """Returns (wav bytes, duration in seconds)."""
    voice = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE

    if speed == 1.0:
        pcm = await _narrate_via_genblaze(text, voice)
    else:
        pcm = await _narrate_direct(text, voice, speed)

    return _to_wav(pcm), _duration(pcm)


def cache_stats() -> dict:
    """Cache hit rate for the run, plus how many renders went through the SDK."""
    hits = _cache.hits if _cache else 0
    misses = _cache.misses if _cache else 0
    looked_up = hits + misses
    return {
        "cacheHits": hits,
        "cacheMisses": misses,
        "cacheHitRate": round(hits / looked_up, 4) if looked_up else 0.0,
        "sdkRenders": stats["sdkRenders"],
        "directRenders": stats["directRenders"],
        "estimatedCostUsd": stats["estimatedCostUsd"],
    }
