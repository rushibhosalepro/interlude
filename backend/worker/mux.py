"""Mix the narration into the original audio, ducked, and write the VTT.

This is how broadcast audio description works: the original soundtrack stays,
dips under each description, and comes back up. The video is never re-rendered.

Ducking is done with a volume filter gated on time ranges rather than a
sidechain compressor. It is deterministic, which matters when the gaps were
chosen precisely: the original drops exactly where narration plays and nowhere
else.
"""

import asyncio
import logging
from pathlib import Path

import storage
from worker import ffmpeg

logger = logging.getLogger(__name__)

# how far the original drops under narration. -12dB roughly, still audible.
DUCK_LEVEL = 0.25


def _timestamp(seconds: float) -> str:
    hours, rest = divmod(max(seconds, 0.0), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def build_vtt(committed: list[dict], gaps_by_id: dict[str, dict]) -> str:
    """The machine readable record. Weak player support, so never the demo output."""
    lines = ["WEBVTT", ""]
    for index, item in enumerate(committed, 1):
        gap = gaps_by_id[item["gapId"]]
        end = gap["start"] + item["durationSeconds"]
        lines += [
            str(index),
            f"{_timestamp(gap['start'])} --> {_timestamp(end)}",
            item["text"],
            "",
        ]
    return "\n".join(lines)


def _filter_graph(placements: list[dict]) -> str:
    """volume-duck the original, delay each narration to its cue, mix them all."""
    windows = "+".join(
        f"between(t,{p['start']:.3f},{p['end']:.3f})" for p in placements
    )
    parts = [f"[0:a]volume={DUCK_LEVEL}:enable='{windows}'[duck]"]

    labels = ["[duck]"]
    for index, placement in enumerate(placements, start=1):
        delay_ms = int(placement["start"] * 1000)
        # adelay needs a value per channel, and amix wants matching layouts
        parts.append(
            f"[{index}:a]aformat=channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}[n{index}]"
        )
        labels.append(f"[n{index}]")

    parts.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0[out]"
    )
    return ";".join(parts)


async def mux(
    project_id: str,
    video_path: str,
    committed: list[dict],
    gaps_by_id: dict[str, dict],
    workdir: Path,
) -> tuple[bytes, float]:
    """Returns (m4a bytes, duration). Narration audio is pulled from B2."""
    placements = []
    inputs: list[str] = []

    for item in committed:
        gap = gaps_by_id[item["gapId"]]
        key = f"projects/{project_id}/attempts/{item['gapId']}/{item['committedAttempt']}/audio.wav"

        local = workdir / f"{item['gapId']}.wav"
        await asyncio.to_thread(
            storage.client.download_file, storage.media_bucket, key, str(local)
        )
        inputs.append(str(local))
        placements.append(
            {
                "start": gap["start"],
                "end": gap["start"] + item["durationSeconds"],
            }
        )

    out_path = workdir / "described-audio.m4a"

    args = ["-v", "error", "-y", "-i", video_path]
    for path in inputs:
        args += ["-i", path]

    if placements:
        args += ["-filter_complex", _filter_graph(placements), "-map", "[out]"]
    else:
        # nothing to narrate, so this is just the original audio re-encoded
        args += ["-map", "0:a"]

    args += ["-c:a", "aac", "-b:a", "128k", str(out_path)]

    logger.info("muxing %d description(s) into the original audio", len(placements))
    await ffmpeg.run(args)

    return out_path.read_bytes(), await ffmpeg.duration(str(out_path))
