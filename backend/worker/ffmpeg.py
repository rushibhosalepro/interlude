"""Locating and running ffmpeg.

Run as a subprocess, never as a library. PyAV bundles its own unsigned ffmpeg
DLLs and Smart App Control blocks those; the standalone binary is unsigned too
but passes, because SAC judges on reputation rather than signature alone.

Always asyncio.create_subprocess_exec, never subprocess.run: a blocking call
here freezes the event loop, and with it the worker and the progress stream,
for the entire encode.
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    pass


def _find(name: str) -> str:
    """ffmpeg on PATH, else the winget install location, else give up."""
    override = os.getenv(f"{name.upper()}_BINARY")
    if override:
        return override

    found = shutil.which(name)
    if found:
        return found

    # winget adds it to PATH but existing shells do not see it until restart
    packages = Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if packages.is_dir():
        for candidate in packages.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"):
            return str(candidate)

    raise FfmpegError(
        f"{name} not found. install it with: winget install --id Gyan.FFmpeg, "
        f"or set {name.upper()}_BINARY to its full path."
    )


async def run(args: list[str], *, binary: str = "ffmpeg") -> str:
    """Run ffmpeg/ffprobe. Returns stdout, raises with stderr on failure."""
    executable = _find(binary)

    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise FfmpegError(
            f"{binary} exited {process.returncode}: {stderr.decode(errors='replace')[-600:]}"
        )

    return stdout.decode(errors="replace")


async def duration(path: str) -> float:
    out = await run(
        [
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        binary="ffprobe",
    )
    return float(out.strip())


async def extract_audio(video: str, out_path: str) -> str:
    """Mono 16kHz mp3. Small enough that a long lecture fits under upload caps."""
    await run([
        "-v", "error", "-y",
        "-i", video,
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        out_path,
    ])
    return out_path
