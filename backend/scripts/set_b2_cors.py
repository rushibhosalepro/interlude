"""Apply CORS rules to the B2 media bucket so browsers can PUT directly to it.

Uses the B2 *native* API. The S3 PutBucketCors call is rejected on any bucket that
already has native rules, which includes anything configured from the B2 web UI:

    InvalidRequest: The bucket contains B2 Native CORS rules.

The web UI presets are download only (s3_get / s3_head) and allow just the
authorization and range headers, so a presigned PUT fails preflight under them.
These rules add s3_put and the content-type header the signed request sends.

Run once per bucket, from the backend directory:

    ./.venv/Scripts/python.exe scripts/set_b2_cors.py
"""

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

key_id = os.getenv("BACKBLAZE_APPLICATION_KEY_ID")
key = os.getenv("BACKBLAZE_APPLICATION_KEY")
bucket_name = os.getenv("BACKBLAZE_MEDIA_BUCKET")

if not all([key_id, key, bucket_name]):
    sys.exit("missing BACKBLAZE_* environment variables, see .env.example")

# replaces every rule on the bucket, so the download rules are restated here
CORS_RULES = [
    {
        "corsRuleName": "interludeS3Browser",
        "allowedOrigins": ORIGINS,
        "allowedOperations": ["s3_put", "s3_get", "s3_head"],
        # the presigned PUT sends content-type, and it is part of the signature
        "allowedHeaders": ["*"],
        "exposeHeaders": ["etag"],
        "maxAgeSeconds": 3600,
    },
    {
        "corsRuleName": "interludeNativeDownload",
        "allowedOrigins": ORIGINS,
        "allowedOperations": ["b2_download_file_by_id", "b2_download_file_by_name"],
        "allowedHeaders": ["authorization", "range"],
        "exposeHeaders": ["etag"],
        "maxAgeSeconds": 3600,
    },
]


def main() -> None:
    auth = (
        httpx.get(
            "https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
            auth=(key_id, key),
            timeout=30,
        )
        .raise_for_status()
        .json()
    )

    api_url = auth["apiInfo"]["storageApi"]["apiUrl"]
    token = auth["authorizationToken"]
    account_id = auth["accountId"]

    buckets = (
        httpx.post(
            f"{api_url}/b2api/v3/b2_list_buckets",
            headers={"Authorization": token},
            json={"accountId": account_id, "bucketName": bucket_name},
            timeout=30,
        )
        .raise_for_status()
        .json()["buckets"]
    )

    if not buckets:
        sys.exit(f"bucket {bucket_name!r} not found")

    bucket_id = buckets[0]["bucketId"]

    print(f"bucket : {bucket_name}")
    print(f"origins: {', '.join(ORIGINS)}")

    updated = (
        httpx.post(
            f"{api_url}/b2api/v3/b2_update_bucket",
            headers={"Authorization": token},
            json={
                "accountId": account_id,
                "bucketId": bucket_id,
                "corsRules": CORS_RULES,
            },
            timeout=30,
        )
        .raise_for_status()
        .json()
    )

    print("\napplied:")
    for rule in updated.get("corsRules", []):
        print(f"  {rule['corsRuleName']}: {rule['allowedOperations']}")


if __name__ == "__main__":
    main()
