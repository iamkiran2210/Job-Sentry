from __future__ import annotations

from ..config import ResumeSettings
from ..errors import StorageError, StorageObjectMissing
from .base import ObjectStorage


class S3Storage(ObjectStorage):
    """Works with AWS S3, MinIO, Cloudflare R2, etc. (set RESUMES_S3_ENDPOINT_URL for non-AWS)."""

    backend_name = "s3"

    def __init__(self, cfg: ResumeSettings) -> None:
        import boto3
        from botocore.config import Config

        if not cfg.s3_bucket:
            raise StorageError("RESUMES_S3_BUCKET is required for the s3 backend")
        self._bucket = cfg.s3_bucket
        self._sse = cfg.s3_server_side_encryption
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg.s3_endpoint_url,
            region_name=cfg.s3_region,
            aws_access_key_id=cfg.s3_access_key_id.get_secret_value()
            if cfg.s3_access_key_id
            else None,
            aws_secret_access_key=cfg.s3_secret_access_key.get_secret_value()
            if cfg.s3_secret_access_key
            else None,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if cfg.s3_force_path_style else "auto"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        extra = {"ServerSideEncryption": self._sse} if self._sse else {}
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                **extra,
            )
        except Exception as exc:
            raise StorageError("put failed") from exc

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise StorageObjectMissing("missing") from exc
            raise StorageError("get failed") from exc
        except Exception as exc:
            raise StorageError("get failed") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise StorageError("delete failed") from exc

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return False
            raise StorageError("head failed") from exc
