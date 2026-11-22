from __future__ import annotations

from enum import StrEnum


class FailureCode(StrEnum):
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    CORRUPT_FILE = "CORRUPT_FILE"
    ENCRYPTED_FILE = "ENCRYPTED_FILE"
    NO_TEXT_FOUND = "NO_TEXT_FOUND"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    OCR_FAILED = "OCR_FAILED"
    STORAGE_ERROR = "STORAGE_ERROR"
    INTEGRITY_ERROR = "INTEGRITY_ERROR"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"
    LLM_INVALID_OUTPUT = "LLM_INVALID_OUTPUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Canned, user-safe text. Raw exception text is never stored or returned.
SAFE_MESSAGES: dict[FailureCode, str] = {
    FailureCode.UNSUPPORTED_CONTENT: "The file type is not supported.",
    FailureCode.CORRUPT_FILE: "The file could not be read; it may be corrupt.",
    FailureCode.ENCRYPTED_FILE: "The file is password-protected.",
    FailureCode.NO_TEXT_FOUND: "No readable text was found in the file.",
    FailureCode.OCR_UNAVAILABLE: "Text recognition is not available for this scanned file.",
    FailureCode.OCR_FAILED: "Text recognition failed for this scanned file.",
    FailureCode.STORAGE_ERROR: "The stored file could not be retrieved.",
    FailureCode.INTEGRITY_ERROR: "The stored file failed an integrity check.",
    FailureCode.LLM_UNAVAILABLE: "The analysis service was temporarily unavailable.",
    FailureCode.LLM_NOT_CONFIGURED: "The analysis service is not configured.",
    FailureCode.LLM_INVALID_OUTPUT: "The analysis result could not be validated.",
    FailureCode.INTERNAL_ERROR: "An unexpected error occurred while processing.",
}


class PipelineError(Exception):
    """Background-processing error. Carries only a code, never content."""

    def __init__(self, code: FailureCode, *, retryable: bool = False) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable


class RejectCode(StrEnum):
    UNSUPPORTED_EXTENSION = "UNSUPPORTED_EXTENSION"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    EMPTY_FILE = "EMPTY_FILE"
    UNSAFE_FILE = "UNSAFE_FILE"
    CORRUPT_FILE = "CORRUPT_FILE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class UploadRejected(Exception):
    def __init__(self, code: RejectCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail  # static, safe text


class DispatchError(Exception):
    """Task could not be handed to the broker."""


class StorageError(Exception):
    pass


class StorageObjectMissing(StorageError):
    pass
