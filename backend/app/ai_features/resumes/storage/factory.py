from __future__ import annotations

from functools import lru_cache

from ..config import ResumeSettings, get_settings
from .base import ObjectStorage


def build_storage(cfg: ResumeSettings) -> ObjectStorage:
    if cfg.storage_backend == "s3":
        from .s3 import S3Storage

        return S3Storage(cfg)
    from .local import LocalStorage

    return LocalStorage(cfg.local_storage_dir)


@lru_cache
def get_storage() -> ObjectStorage:
    return build_storage(get_settings())
