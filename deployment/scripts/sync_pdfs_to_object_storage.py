"""Upload data_extraction/data/raw/<TICKER>/*.pdf into S3-compatible object storage
(MinIO locally, or real S3/R2 in the cloud) -- Phase 24's "object storage" service.

finqa_v2's document ingestion (finqa_v2/documents/backfill.py) still reads these PDFs
from local disk; this script doesn't change that. It gives the filing PDFs a second,
network-reachable home -- useful for a deployment where the raw PDF directory isn't
available on whatever host runs a rebuild, and as the natural next step (not done
here) if ingestion is later pointed at object storage instead of local disk.

Usage (against the local docker-compose MinIO -- use the MINIO_ROOT_USER/PASSWORD from
your deployment/compose/.env):
    pip install boto3
    python deployment/scripts/sync_pdfs_to_object_storage.py \\
        --endpoint-url http://localhost:9000 --access-key finqa --secret-key <MINIO_ROOT_PASSWORD>

Usage (against real AWS S3 -- omit --endpoint-url, use your usual AWS credentials):
    python deployment/scripts/sync_pdfs_to_object_storage.py --bucket my-bucket
"""
from __future__ import annotations

import argparse
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RAW_DIR = _REPO_ROOT / "data_extraction" / "data" / "raw"


def sync(*, bucket: str, endpoint_url: str | None, access_key: str | None,
         secret_key: str | None, dry_run: bool = False) -> dict:
    pdfs = sorted(_RAW_DIR.glob("*/*.pdf"))
    if dry_run:
        return {"bucket": bucket, "would_upload": len(pdfs), "uploaded": 0, "skipped": 0}

    import boto3

    s3 = boto3.client(
        "s3", endpoint_url=endpoint_url,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    existing = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            existing.add(obj["Key"])

    uploaded = skipped = 0
    for pdf in pdfs:
        key = f"{pdf.parent.name}/{pdf.name}"          # <TICKER>/<file>.pdf
        if key in existing:
            skipped += 1
            continue
        s3.upload_file(str(pdf), bucket, key)
        uploaded += 1

    return {"bucket": bucket, "would_upload": 0, "uploaded": uploaded, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bucket", default="filing-pdfs")
    ap.add_argument("--endpoint-url", default=None, help="S3-compatible endpoint (e.g. http://localhost:9000 for MinIO); omit for real AWS S3.")
    ap.add_argument("--access-key", default=None)
    ap.add_argument("--secret-key", default=None)
    ap.add_argument("--dry-run", action="store_true", help="Count what would be uploaded; makes no network calls.")
    args = ap.parse_args()

    if not _RAW_DIR.is_dir():
        print(f"no raw PDF directory at {_RAW_DIR} -- nothing to sync")
        return 1

    result = sync(bucket=args.bucket, endpoint_url=args.endpoint_url,
                  access_key=args.access_key, secret_key=args.secret_key, dry_run=args.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
