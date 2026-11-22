"""Phase 3 settings. Independent of Phase 1 settings; every value is env-driven (prefix RESUMES_)."""

from __future__ import annotations

from functools import lru_cache
import os
import shutil
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_tesseract_cmd() -> str:
    found = shutil.which("tesseract")
    if found:
        return found
    for c in (
            os.path.expanduser("~/.local/bin/tesseract"),
            "/usr/local/bin/tesseract",
            "/usr/bin/tesseract",
            "/opt/homebrew/bin/tesseract",
    ):
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "tesseract"


class ResumeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESUMES_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # --- upload limits ---
    max_upload_bytes: int = 10 * 1024 * 1024
    max_files_per_request: int = 20
    max_image_pixels: int = 40_000_000
    max_docx_uncompressed_bytes: int = 100 * 1024 * 1024
    max_docx_entries: int = 2000

    # --- storage ---
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./var/resume_storage"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None  # e.g. http://minio:9000
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = True
    s3_server_side_encryption: str | None = None  # "AES256" or "aws:kms"

    # --- celery / pipeline ---
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_queue: str = "resumes"
    task_max_attempts: int = 4
    task_retry_base_seconds: int = 30
    task_soft_time_limit: int = 300
    lease_seconds: int = 600  # must exceed the task hard time limit
    stuck_after_seconds: int = 900
    manual_retry_limit: int = 5
    log_tracebacks: bool = False  # tracebacks may contain resume text; keep off in prod

    # --- parsing / OCR ---
    pdf_max_pages: int = 40
    pdf_render_dpi: int = 200
    min_chars_per_page: int = 40
    max_text_chars: int = 100_000
    ocr_enabled: bool = True
    ocr_languages: str = "eng"
    tesseract_cmd: str = Field(default_factory=_detect_tesseract_cmd)
    ocr_timeout_seconds: int = 60
    ocr_low_confidence: float = 35.0
    docx_max_ocr_images: int = 5


@lru_cache
def get_settings() -> ResumeSettings:
    return ResumeSettings()
