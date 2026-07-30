"""Shared B2 client and small helpers over it.

Lives outside routes/ so the worker and the API can use the same client without
importing each other.

Every function here is blocking (boto3 has no async API). Call them from async
code with `asyncio.to_thread`, never directly, or the event loop stalls and the
progress stream freezes.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

application_key_id = os.getenv("BACKBLAZE_APPLICATION_KEY_ID")
application_key = os.getenv("BACKBLAZE_APPLICATION_KEY")
endpoint_url = os.getenv("BACKBLAZE_ENDPOINT_URL")
region = os.getenv("BACKBLAZE_REGION")
media_bucket = os.getenv("BACKBLAZE_MEDIA_BUCKET")
compliance_bucket = os.getenv("BACKBLAZE_COMPLIANCE_BUCKET")

# fail at import rather than handing out broken presigned URLs at request time
_required = {
    "BACKBLAZE_APPLICATION_KEY_ID": application_key_id,
    "BACKBLAZE_APPLICATION_KEY": application_key,
    "BACKBLAZE_ENDPOINT_URL": endpoint_url,
    "BACKBLAZE_REGION": region,
    "BACKBLAZE_MEDIA_BUCKET": media_bucket,
}

_missing = sorted(name for name, value in _required.items() if not value)

if _missing:
    raise RuntimeError(
        f"missing required environment variables: {', '.join(_missing)}. "
        "copy .env.example to .env and fill them in."
    )


client = boto3.client(
    "s3",
    aws_access_key_id=application_key_id,
    aws_secret_access_key=application_key,
    region_name=region,
    endpoint_url=endpoint_url,
)


# Genblaze reads its own variable names for the same credentials. Copy ours
# across so there is one place to change a key, not two that can drift apart.
# setdefault, so an explicitly set B2_* in .env still wins.
for _genblaze_name, _our_value in {
    "B2_KEY_ID": application_key_id,
    "B2_APP_KEY": application_key,
    "B2_BUCKET": media_bucket,
    "B2_REGION": region,
}.items():
    if _our_value and not os.getenv(_genblaze_name):
        os.environ[_genblaze_name] = _our_value

NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


def object_exists(key: str, bucket: str | None = None) -> bool:
    """True if the object is there. This is how the worker derives its progress."""
    try:
        client.head_object(Bucket=bucket or media_bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in NOT_FOUND_CODES:
            return False
        raise


def put_json(key: str, data: dict, bucket: str | None = None) -> None:
    client.put_object(
        Bucket=bucket or media_bucket,
        Key=key,
        Body=json.dumps(data, indent=2).encode(),
        ContentType="application/json",
    )


def get_json(key: str, bucket: str | None = None) -> dict | None:
    try:
        resp = client.get_object(Bucket=bucket or media_bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in NOT_FOUND_CODES:
            return None
        raise
    return json.loads(resp["Body"].read())


def put_bytes(key: str, body: bytes, content_type: str, bucket: str | None = None) -> None:
    client.put_object(
        Bucket=bucket or media_bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def list_child_prefixes(prefix: str, bucket: str | None = None) -> list[str]:
    """The 'folder' names directly under `prefix`, e.g. every job id under jobs/."""
    paginator = client.get_paginator("list_objects_v2")
    names: list[str] = []
    for page in paginator.paginate(
        Bucket=bucket or media_bucket, Prefix=prefix, Delimiter="/"
    ):
        for entry in page.get("CommonPrefixes", []):
            names.append(entry["Prefix"][len(prefix) :].rstrip("/"))
    return names
