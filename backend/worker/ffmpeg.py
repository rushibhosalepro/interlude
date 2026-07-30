"""Locating and running ffmpeg.

Run as a subprocess, never as a library. PyAV bundles its own unsigned ffmpeg
DLLs and Smart App Control blocks those; the standalone binary is unsigned too
but passes, because SAC judges on reputation rather than signature alone.

Run on a worker thread, never on the event loop directly. A plain subprocess.run
here would freeze the loop, and with it the worker and the progress stream, for
the entire encode.

asyncio.create_subprocess_exec would be the obvious choice, but it raises
NotImplementedError on Windows under a SelectorEventLoop, which is what uvicorn
runs. TestClient uses asyncio.run and gets a ProactorEventLoop, so that failure
only shows up under the real server. asyncio.to_thread works on either.
"""

import asyncio
import logging
import os
import shutil
import subprocess
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


def _run_blocking(executable: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [executable, *args],
        capture_output=True,
        # no shell, so a filename with spaces or quotes cannot become an argument
        shell=False,
    )


async def run(args: list[str], *, binary: str = "ffmpeg") -> str:
    """Run ffmpeg/ffprobe on a thread. Returns stdout, raises with stderr."""
    executable = _find(binary)

    result = await asyncio.to_thread(_run_blocking, executable, args)

    if result.returncode != 0:
        raise FfmpegError(
            f"{binary} exited {result.returncode}: "
            f"{result.stderr.decode(errors='replace')[-600:]}"
        )

    return result.stdout.decode(errors="replace")


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
