"""Object storage through the S3 API only, so MinIO, R2, and S3 are interchangeable. Nothing
here is MinIO-specific. Objects are private; files reach users through the API."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings


class StorageError(RuntimeError):
    """The object store failed or isn't reachable."""


class StorageNotConfiguredError(StorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    data: bytes
    content_type: str


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> StoredObject: ...


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            # Path-style addressing works on MinIO, R2, and S3 without bucket DNS.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Could not store object: {type(exc).__name__}") from exc

    def get(self, key: str) -> StoredObject:
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
            return StoredObject(
                data=obj["Body"].read(),
                content_type=obj.get("ContentType") or "application/octet-stream",
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Could not read object: {type(exc).__name__}") from exc


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    if not settings.s3_bucket:
        raise StorageNotConfiguredError("Object storage is not configured (S3_BUCKET)")
    return S3Storage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )
