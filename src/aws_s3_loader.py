"""
aws_s3_loader.py
-----------------
Storage layer (Step 3): lands the raw sales.csv extract in Amazon S3.

Why S3 here: S3 is the standard "landing zone" for raw files in a
data-engineering architecture -- cheap, durable, versioned, and it decouples
the source system from the warehouse. Snowflake later reads directly from
this bucket through an external stage, so this script's only job is to get
the raw file into S3 reliably and log/handle failures.

Usage:
    python src/aws_s3_loader.py --file data/sales.csv

Requires AWS credentials to be set (see .env.example). If credentials are
not configured, the script fails fast with a clear error instead of
pretending to succeed.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError:  # pragma: no cover
    boto3 = None

from config import aws_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aws_s3_loader")


class S3UploadError(Exception):
    """Raised when the raw file cannot be landed in S3."""


def upload_sales_file(local_path: str, bucket: str = None, prefix: str = None) -> str:
    """
    Upload a local CSV file to the configured S3 bucket/prefix.

    Returns the resulting s3:// URI on success. Raises S3UploadError on any
    failure (missing file, missing credentials, network/API error) so
    calling code (the pipeline orchestrator) can decide how to react.
    """
    if boto3 is None:
        raise S3UploadError(
            "boto3 is not installed. Run `pip install boto3` to enable S3 uploads."
        )

    bucket = bucket or aws_config.bucket_name
    prefix = prefix or aws_config.raw_prefix

    src = Path(local_path)
    if not src.exists():
        raise S3UploadError(f"Local file not found: {local_path}")

    if not aws_config.has_credentials and not os.getenv("AWS_PROFILE"):
        raise S3UploadError(
            "No AWS credentials configured. Set AWS_ACCESS_KEY_ID / "
            "AWS_SECRET_ACCESS_KEY (or AWS_PROFILE) in your environment."
        )

    key = f"{prefix.rstrip('/')}/{src.name}"

    try:
        client = boto3.client(
            "s3",
            region_name=aws_config.region_name,
            aws_access_key_id=aws_config.access_key_id or None,
            aws_secret_access_key=aws_config.secret_access_key or None,
        )
        client.upload_file(str(src), bucket, key)
        uri = f"s3://{bucket}/{key}"
        logger.info("Uploaded %s -> %s", src, uri)
        return uri
    except NoCredentialsError as exc:
        raise S3UploadError("AWS credentials rejected/missing.") from exc
    except (BotoCoreError, ClientError) as exc:
        raise S3UploadError(f"S3 upload failed: {exc}") from exc


def main():
    parser = argparse.ArgumentParser(description="Upload sales.csv to the S3 raw landing zone.")
    parser.add_argument("--file", default="data/sales.csv", help="Path to the local CSV file.")
    parser.add_argument("--bucket", default=None, help="Override the target S3 bucket.")
    parser.add_argument("--prefix", default=None, help="Override the target S3 key prefix.")
    args = parser.parse_args()

    try:
        uri = upload_sales_file(args.file, args.bucket, args.prefix)
        print(f"OK: {uri}")
    except S3UploadError as exc:
        logger.error(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
