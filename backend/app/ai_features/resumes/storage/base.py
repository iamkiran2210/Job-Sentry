from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class ObjectStorage(ABC):
    """Synchronous byte store. Call via asyncio.to_thread from async code."""

    backend_name: str

    @abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


def build_key(company_id, job_id, resume_id, extension: str) -> str:
    """Use only the server-generated resume UUID as the opaque storage key."""
    try:
        return str(UUID(str(resume_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("resume_id must be a UUID") from exc
