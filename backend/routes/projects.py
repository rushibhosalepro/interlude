"""Finished runs, for the gallery and the player.

Judges land on a populated screen rather than an empty uploader, which
ARCHITECTURE.md lists as a demo requirement.

Audio is served by presigned GET straight from B2. The API hands out a URL and
steps out of the way, so storage is the delivery surface rather than something
the server proxies.
"""

import asyncio
import logging
import re
import time

from fastapi import APIRouter, HTTPException

import storage

logger = logging.getLogger(__name__)

router = APIRouter()

PLAYBACK_URL_TTL = 3600  # seconds

# a project is only listed once publish has written its manifest receipt
MANIFEST_KEY = re.compile(
    r"^projects/(?P<projectId>[0-9a-f]{32})/final/(?P<videoId>[0-9a-f]{32})/manifest\.json$"
)


def _presign_get(key: str, download_as: str | None = None) -> str:
    params = {"Bucket": storage.media_bucket, "Key": key}
    if download_as:
        # the HTML download attribute is ignored cross origin, so the header has
        # to come from the signed URL or clicking it just navigates to the video
        params["ResponseContentDisposition"] = (
            f'attachment; filename="{download_as}"'
        )
    return storage.client.generate_presigned_url(
        "get_object", Params=params, ExpiresIn=PLAYBACK_URL_TTL
    )


def _list_finished() -> list[tuple[str, str]]:
    """Finished runs, newest first.

    B2 lists lexicographically by key, and project ids are random hex, so the
    listing order is meaningless. Sort on when the manifest receipt was written,
    which is the moment the run actually finished.
    """
    paginator = storage.client.get_paginator("list_objects_v2")
    found = []
    for page in paginator.paginate(Bucket=storage.media_bucket, Prefix="projects/"):
        for entry in page.get("Contents", []):
            match = MANIFEST_KEY.match(entry["Key"])
            if match:
                found.append(
                    (entry["LastModified"], match["projectId"], match["videoId"])
                )
    found.sort(key=lambda row: row[0], reverse=True)
    return [(project_id, video_id) for _, project_id, video_id in found]


def _load_project(project_id: str, video_id: str) -> dict | None:
    base = f"projects/{project_id}"
    analysis = f"{base}/analysis/{video_id}"
    final = f"{base}/final/{video_id}"

    descriptions = storage.get_json(f"{analysis}/descriptions.json")
    decisions = storage.get_json(f"{analysis}/decisions.json")
    gaps = storage.get_json(f"{analysis}/gaps.json")
    transcript = storage.get_json(f"{analysis}/transcript.json")
    coverage = storage.get_json(f"{analysis}/coverage.json")
    receipt = storage.get_json(f"{final}/manifest.json")

    if not all([descriptions, decisions, gaps, receipt]):
        return None

    gaps_by_id = {g["id"]: g for g in gaps["gaps"]}
    committed = [r for r in descriptions["results"] if r["status"] == "committed"]
    narrated_ids = {r["gapId"] for r in committed}

    # coverage.json records which fact indices were recovered but not their text,
    # so pair them back up with the facts the analyse stage found
    all_facts = [
        fact for d in decisions["decisions"] for fact in (d.get("facts") or [])
    ]
    recovered = set((coverage or {}).get("recoveredAfter") or [])
    fact_list = [
        {"text": text, "recovered": index in recovered}
        for index, text in enumerate(all_facts)
    ]

    return {
        "projectId": project_id,
        "videoId": video_id,
        "durationSeconds": (transcript or {}).get("duration"),
        "language": (transcript or {}).get("language"),
        "videoUrl": _presign_get(f"{final}/described.mp4"),
        # the untouched upload, so Original vs Described is a real comparison
        "originalUrl": _presign_get(f"{base}/source/{video_id}.mp4"),
        "downloadUrl": _presign_get(
            f"{final}/described.mp4", download_as=f"described-{video_id[:8]}.mp4"
        ),
        "audioUrl": _presign_get(f"{final}/described-audio.m4a"),
        "vttUrl": _presign_get(f"{final}/descriptions.vtt"),
        "sourceUrl": _presign_get(f"{base}/source/{video_id}.mp4"),
        "expiresIn": PLAYBACK_URL_TTL,
        "metrics": {
            "gapsFound": gaps["count"],
            "gapSeconds": gaps["totalGapSeconds"],
            "toFill": decisions.get("toFill", 0),
            "toSkip": decisions.get("toSkip", 0),
            "density": decisions.get("density", 0),
            "firstPassFitRate": descriptions.get("firstPassFitRate", 0),
            "finalFitRate": descriptions.get("finalFitRate", 0),
            "totalAttempts": descriptions.get("totalAttempts", 0),
            # narration that ran past its gap would be spoken over the lecturer.
            # should be zero by construction, but report it rather than assert it.
            "overruns": sum(
                1
                for r in committed
                if r["gapId"] in gaps_by_id
                and r["durationSeconds"] > gaps_by_id[r["gapId"]]["duration"]
            ),
        },
        # every gap, narrated or not, so the scrubber can band them
        "gaps": [
            {
                "gapId": g["id"],
                "start": g["start"],
                "end": g["end"],
                "duration": g["duration"],
                "kind": g["kind"],
                "narrated": g["id"] in narrated_ids,
            }
            for g in gaps["gaps"]
        ],
        "coverage": {
            "before": (coverage or {}).get("coverageBefore", 0),
            "after": (coverage or {}).get("coverageAfter", 0),
            "checker": (coverage or {}).get("model"),
            "facts": fact_list,
        },
        "descriptions": [
            {
                "gapId": r["gapId"],
                "text": r["text"],
                "startsAt": gaps_by_id[r["gapId"]]["start"],
                "durationSeconds": r["durationSeconds"],
                "availableSeconds": gaps_by_id[r["gapId"]]["duration"],
                "attemptCount": len(r["attempts"]),
                "firstPass": r["firstPass"],
                # the full ladder, so the rewrite loop can be shown in line
                "attempts": [
                    {
                        "n": a["attempt"],
                        "text": a["text"],
                        "words": a["words"],
                        "durationSeconds": a["durationSeconds"],
                        "targetSeconds": a["targetSeconds"],
                        "fits": a["fits"],
                        "speed": a.get("speed", 1.0),
                    }
                    for a in r["attempts"]
                ],
            }
            for r in committed
            if r["gapId"] in gaps_by_id
        ],
        "provenance": {
            "manifestKey": receipt.get("manifestKey"),
            "bucket": receipt.get("bucket"),
            "canonicalHash": receipt.get("canonicalHash"),
            "steps": receipt.get("steps"),
            "retainUntil": receipt.get("retainUntil"),
            "lockMode": receipt.get("lockMode", "GOVERNANCE"),
        },
    }


# listing the bucket and reading five artifacts per project costs ~8s cold, which
# is far too slow for the page judges land on. the answer only changes when a job
# finishes, so cache it and let the uploader invalidate on completion.
_cache: dict = {"at": 0.0, "payload": None}
CACHE_TTL = 120  # seconds


def invalidate_cache() -> None:
    _cache["at"] = 0.0


@router.get("/projects")
async def list_projects(limit: int = 12, refresh: bool = False):
    """Finished runs, newest last. Each carries playable URLs and its metrics."""
    now = time.monotonic()
    if not refresh and _cache["payload"] and now - _cache["at"] < CACHE_TTL:
        return _cache["payload"]

    finished = await asyncio.to_thread(_list_finished)

    # one B2 round trip per artifact, so load the projects concurrently
    loaded = await asyncio.gather(
        *(
            asyncio.to_thread(_load_project, project_id, video_id)
            for project_id, video_id in finished[-limit:]
        ),
        return_exceptions=True,
    )

    projects = []
    for item in loaded:
        if isinstance(item, Exception):
            logger.warning("skipping unreadable project: %s", item)
            continue
        if item:
            projects.append(item)

    payload = {"projects": projects, "count": len(projects)}
    _cache["at"], _cache["payload"] = now, payload
    return payload


@router.get("/projects/{project_id}/{video_id}")
async def get_project(project_id: str, video_id: str):
    project = await asyncio.to_thread(_load_project, project_id, video_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found or unfinished")
    return project
