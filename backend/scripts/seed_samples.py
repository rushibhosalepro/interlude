"""Put a clip into samples/ so judges can run it with one click.

    ./.venv/Scripts/python.exe scripts/seed_samples.py <file-or-b2-key> --id my-clip

Trims to the live-processing cap if needed, since a sample that the pipeline
would reject is worse than no sample. Duration and title ride along as object
metadata so the API does not have to probe on every list.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage  # noqa: E402

MAX_SECONDS = float(os.getenv("MAX_CLIP_SECONDS", "90"))


def _ffmpeg(name: str) -> str:
    from shutil import which

    found = which(name)
    if found:
        return found
    packages = Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for candidate in packages.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"):
        return str(candidate)
    sys.exit(f"{name} not found. install it with: winget install --id Gyan.FFmpeg")


def duration(path: Path) -> float:
    out = subprocess.run(
        [_ffmpeg("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="local file, or an existing key in the media bucket")
    parser.add_argument("--id", required=True, help="sample id, lowercase and hyphens")
    parser.add_argument("--title", help="shown in the UI, defaults to the id")
    parser.add_argument("--seconds", type=float, default=MAX_SECONDS,
                        help=f"trim length, default {MAX_SECONDS:g}")
    parser.add_argument("--start", type=float, default=0.0,
                        help="seconds into the source to start the trim")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="interlude-sample-") as tmp:
        workdir = Path(tmp)
        local = workdir / "input.mp4"

        if Path(args.source).exists():
            local.write_bytes(Path(args.source).read_bytes())
            print(f"read local file {args.source}")
        else:
            storage.client.download_file(storage.media_bucket, args.source, str(local))
            print(f"pulled {args.source} from {storage.media_bucket}")

        original = duration(local)
        target = min(args.seconds, MAX_SECONDS)

        if original > target or args.start:
            trimmed = workdir / "trimmed.mp4"
            # re-encode rather than copy: a stream copy cuts at the nearest
            # keyframe, which can leave a second of black at the start
            subprocess.run(
                [_ffmpeg("ffmpeg"), "-v", "error", "-y",
                 "-ss", str(args.start), "-i", str(local),
                 "-t", str(target), "-c:v", "libx264", "-preset", "veryfast",
                 "-c:a", "aac", str(trimmed)],
                check=True,
            )
            local = trimmed
            print(f"trimmed {original:.1f}s -> {duration(local):.1f}s")
        else:
            print(f"{original:.1f}s, already within the {target:g}s cap")

        key = f"samples/{args.id}.mp4"
        storage.client.put_object(
            Bucket=storage.media_bucket,
            Key=key,
            Body=local.read_bytes(),
            ContentType="video/mp4",
            Metadata={
                "title": args.title or args.id.replace("-", " "),
                "seconds": f"{duration(local):.3f}",
            },
        )
        print(f"seeded {key} ({local.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
