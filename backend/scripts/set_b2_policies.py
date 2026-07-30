"""Lifecycle rules and prefix-scoped application keys.

Two one-off hardening jobs:

    ./.venv/Scripts/python.exe scripts/set_b2_policies.py --lifecycle
    ./.venv/Scripts/python.exe scripts/set_b2_policies.py --keys

Lifecycle uses the B2 native API. The S3 PutBucketLifecycleConfiguration call is
rejected on buckets that already carry native rules, the same trap as CORS.

Keys are printed once and are never retrievable again.
"""

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

KEY_ID = os.getenv("BACKBLAZE_APPLICATION_KEY_ID")
APP_KEY = os.getenv("BACKBLAZE_APPLICATION_KEY")
MEDIA = os.getenv("BACKBLAZE_MEDIA_BUCKET")
COMPLIANCE = os.getenv("BACKBLAZE_COMPLIANCE_BUCKET")

RETAIN_ATTEMPT_DAYS = int(os.getenv("ATTEMPTS_RETENTION_DAYS", "30"))

# The prefix attempts would need to sit under for a lifecycle rule to reach
# them. B2 matches from the start of the key and cannot wildcard, so
# projects/{projectId}/attempts/... is unreachable by any single rule.
EXPIRABLE_PREFIX = "attempts/"


def authorize() -> dict:
    if not (KEY_ID and APP_KEY):
        sys.exit("BACKBLAZE_APPLICATION_KEY_ID / _KEY missing, see .env.example")
    return (
        httpx.get(
            "https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
            auth=(KEY_ID, APP_KEY),
            timeout=30,
        )
        .raise_for_status()
        .json()
    )


def _api(auth: dict) -> tuple[str, dict]:
    return auth["apiInfo"]["storageApi"]["apiUrl"], {
        "Authorization": auth["authorizationToken"]
    }


def find_bucket(auth: dict, name: str) -> dict:
    url, headers = _api(auth)
    buckets = (
        httpx.post(
            f"{url}/b2api/v3/b2_list_buckets",
            headers=headers,
            json={"accountId": auth["accountId"], "bucketName": name},
            timeout=30,
        )
        .raise_for_status()
        .json()["buckets"]
    )
    if not buckets:
        sys.exit(f"bucket {name!r} not found")
    return buckets[0]


def _sample_layout(auth: dict, bucket: dict) -> tuple[int, int]:
    """(keys starting with attempts/, keys with attempts nested inside)."""
    url, headers = _api(auth)
    body = {"bucketId": bucket["bucketId"], "maxFileCount": 1000}
    files = (
        httpx.post(f"{url}/b2api/v3/b2_list_file_names", headers=headers, json=body, timeout=60)
        .raise_for_status()
        .json()["files"]
    )
    names = [f["fileName"] for f in files]
    top = sum(1 for n in names if n.startswith(EXPIRABLE_PREFIX))
    nested = sum(1 for n in names if "/attempts/" in n)
    return top, nested


def apply_lifecycle(auth: dict) -> None:
    url, headers = _api(auth)
    bucket = find_bucket(auth, MEDIA)
    top, nested = _sample_layout(auth, bucket)

    print(f"bucket {MEDIA}")
    print(f"  keys under {EXPIRABLE_PREFIX!r:>12} : {top}")
    print(f"  keys with /attempts/ nested : {nested}")
    print()

    if nested and not top:
        print("REFUSING TO APPLY. B2 lifecycle rules match a prefix from the start")
        print("of the key and cannot wildcard the project id, so no single rule can")
        print("reach projects/{projectId}/attempts/... .")
        print()
        print("A rule on 'projects/' would match final/ and analysis/ as well and")
        print("delete the deliverables, so that is not a workaround.")
        print()
        print("Two ways forward:")
        print("  1. Move attempts to a top level prefix, attempts/{projectId}/...")
        print("     Then the rule below applies cleanly. This is the small change.")
        print("  2. One rule per project. Bounded by B2's per-bucket rule limit and")
        print("     needs re-applying on every new project, so not recommended.")
        print()
        print("The rule that would be applied once the layout allows it:")
        print(f"  {{'fileNamePrefix': '{EXPIRABLE_PREFIX}',")
        print(f"   'daysFromUploadingToHiding': {RETAIN_ATTEMPT_DAYS},")
        print("   'daysFromHidingToDeleting': 1}")
        raise SystemExit(1)

    rules = [
        {
            "fileNamePrefix": EXPIRABLE_PREFIX,
            "daysFromUploadingToHiding": RETAIN_ATTEMPT_DAYS,
            "daysFromHidingToDeleting": 1,
        }
    ]

    updated = (
        httpx.post(
            f"{url}/b2api/v3/b2_update_bucket",
            headers=headers,
            json={
                "accountId": auth["accountId"],
                "bucketId": bucket["bucketId"],
                "lifecycleRules": rules,
            },
            timeout=30,
        )
        .raise_for_status()
        .json()
    )

    print("applied:")
    for rule in updated.get("lifecycleRules", []):
        print(
            f"  {rule['fileNamePrefix']!r}: hide after "
            f"{rule.get('daysFromUploadingToHiding')} day(s), "
            f"delete {rule.get('daysFromHidingToDeleting')} day(s) later"
        )
    print()
    print("final/ and analysis/ carry no rule, so nothing expires them.")


def create_scoped_key(auth: dict, bucket_name: str, prefix: str, caps: list[str]) -> None:
    url, headers = _api(auth)
    bucket = find_bucket(auth, bucket_name)

    body = {
        "accountId": auth["accountId"],
        "capabilities": caps,
        "keyName": f"interlude-{bucket_name}"[:100],
        "bucketId": bucket["bucketId"],
    }
    if prefix:
        body["namePrefix"] = prefix

    created = (
        httpx.post(f"{url}/b2api/v3/b2_create_key", headers=headers, json=body, timeout=30)
        .raise_for_status()
        .json()
    )

    print(f"--- {bucket_name} ---")
    print(f"  keyName      : {created['keyName']}")
    print(f"  namePrefix   : {created.get('namePrefix') or '(whole bucket)'}")
    print(f"  capabilities : {', '.join(created['capabilities'])}")
    print(f"  keyID        : {created['applicationKeyId']}")
    print(f"  key          : {created['applicationKey']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lifecycle", action="store_true", help="apply lifecycle rules")
    parser.add_argument("--keys", action="store_true", help="mint prefix-scoped keys")
    args = parser.parse_args()

    if not (args.lifecycle or args.keys):
        parser.error("pass --lifecycle or --keys")

    auth = authorize()

    if args.lifecycle:
        apply_lifecycle(auth)

    if args.keys:
        print("Shown once, never retrievable again. Copy straight into .env.\n")
        # the app reads, writes and presigns media
        create_scoped_key(
            auth,
            MEDIA,
            prefix="",
            caps=["listBuckets", "listFiles", "readFiles", "writeFiles",
                  "deleteFiles", "shareFiles"],
        )
        # compliance is append only from the app's side. No deleteFiles and no
        # bypassGovernance, so this key cannot remove a locked manifest even by
        # asking for a bypass. That closes the hole the current shared key leaves.
        create_scoped_key(
            auth,
            COMPLIANCE,
            prefix="compliance/",
            caps=["listBuckets", "listFiles", "readFiles", "writeFiles",
                  "writeFileRetentions", "readFileRetentions"],
        )


if __name__ == "__main__":
    main()
