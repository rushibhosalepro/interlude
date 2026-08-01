"""Copy the finished demo clips out of B2 into the frontend's public/demos.

Run once before deploying. The curated demos then play from the frontend CDN
(Vercel) instead of pulling from B2 on every view, which keeps demo playback off
the B2 download cap and makes it faster and independent of B2 uptime. Judge
created runs are not cached and keep streaming from B2.

    ./.venv/Scripts/python.exe scripts/cache_demos.py

Writes, for each finished project:
    ../frontend/public/demos/{videoId}.mp4        described video, web-compressed
    ../frontend/public/demos/manifest.json        the ids the frontend swaps

Only the described video is bundled, and it is re-encoded to a web-friendly size
(masters can be hundreds of MB, too large to ship in the deploy). The original
upload is not cached; the Original toggle keeps streaming from B2, which is a
brief click. Needs the B2 caps not to be exhausted; if it errors with
AccessDenied, raise the download bandwidth and Class B/C transaction caps in the
B2 console and try again.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage  # noqa: E402
import routes.projects as projects  # noqa: E402
from worker.ffmpeg import _find  # noqa: E402

OUT = Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "demos"


def _compress(src: Path, dest: Path) -> None:
    """720p-cap, faststart web copy. crf 26 keeps it small without visible loss;
    128k audio preserves the narration."""
    subprocess.run(
        [_find("ffmpeg"), "-v", "error", "-y", "-i", str(src),
         "-vf", "scale='min(1280,iw)':-2",
         "-c:v", "libx264", "-crf", "26", "-preset", "medium",
         "-movflags", "+faststart", "-c:a", "aac", "-b:a", "128k", str(dest)],
        check=True,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    finished = projects._list_finished()
    if not finished:
        sys.exit("no finished projects to cache")

    ids = []
    total = 0.0
    with tempfile.TemporaryDirectory(prefix="interlude-cache-") as tmp:
        for project_id, video_id in finished:
            described = f"projects/{project_id}/final/{video_id}/described.mp4"
            raw = Path(tmp) / f"{video_id}.mp4"
            out = OUT / f"{video_id}.mp4"

            try:
                storage.client.download_file(storage.media_bucket, described, str(raw))
                _compress(raw, out)
            except Exception as exc:  # noqa: BLE001
                print(f"skip {video_id[:8]}: {exc}")
                continue

            mb = out.stat().st_size / 1_048_576
            ids.append(video_id)
            total += mb
            print(f"cached {video_id[:8]}  -> {mb:.1f}MB")

    (OUT / "manifest.json").write_text(json.dumps({"ids": ids}, indent=2))
    print(f"\nwrote manifest with {len(ids)} demo(s), {total:.0f} MB total")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
