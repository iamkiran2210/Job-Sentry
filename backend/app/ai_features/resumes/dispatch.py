from __future__ import annotations

import uuid
from typing import Protocol

from .errors import DispatchError


class Dispatcher(Protocol):
    def enqueue(self, resume_id: uuid.UUID) -> None: ...


class CeleryDispatcher:
    def enqueue(self, resume_id: uuid.UUID) -> None:
        from .config import get_settings
        from .tasks import process_resume_task

        try:
            process_resume_task.apply_async(
                args=[str(resume_id)],
                queue=get_settings().celery_queue,
                retry=True,
                retry_policy={
                    "max_retries": 1,
                    "interval_start": 0,
                    "interval_step": 0.2,
                },
            )
        except Exception:
            raise DispatchError("broker unavailable") from None


def get_dispatcher() -> Dispatcher:
    return CeleryDispatcher()
