"""Storage abstraction: local disk or Cloudflare R2 (S3-compatible)."""

import hashlib
import os
import shutil
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from apps.api.config import (
    LOCAL_STORAGE_PATH,
    R2_ACCESS_KEY_ID,
    R2_BUCKET_NAME,
    R2_ENDPOINT_URL,
    R2_SECRET_ACCESS_KEY,
    is_r2_available,
)

import logging

logger = logging.getLogger(__name__)


class LocalStorage:
    def __init__(self):
        self.base_path = LOCAL_STORAGE_PATH
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, key: str) -> str:
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def save_file(self, src_path: str, key: str) -> str:
        dest = self.base_path / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest)
        return str(dest)

    def get_path(self, key: str) -> str:
        return str(self.base_path / key)

    def get_url(self, key: str) -> str:
        return f"/api/files/{key}"

    def exists(self, key: str) -> bool:
        return (self.base_path / key).exists()

    def delete(self, key: str) -> bool:
        path = self.base_path / key
        if path.exists():
            path.unlink()
            return True
        return False


class R2Storage:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
        self.bucket = R2_BUCKET_NAME

    def save(self, data: bytes, key: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def save_file(self, src_path: str, key: str) -> str:
        self.client.upload_file(src_path, self.bucket, key)
        return key

    def get_url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=3600,
        )

    def get_path(self, key: str) -> str:
        """Download from R2 to a local temp path and return it.

        Cached: if the file already exists locally it is not re-downloaded.
        """
        local = Path(f"/tmp/r2_cache/{key}")
        local.parent.mkdir(parents=True, exist_ok=True)
        if not local.exists():
            logger.info(f"Downloading from R2: {key} -> {local}")
            self.client.download_file(self.bucket, key, str(local))
            logger.info(f"Download complete: {key} ({local.stat().st_size} bytes)")
        return str(local)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


def get_storage():
    if is_r2_available():
        logger.info("Using R2 storage")
        return R2Storage()
    logger.info("Using local storage")
    return LocalStorage()


# Singleton
storage = get_storage()
