"""
Celery app. Worker:  celery -A app.features.resumes.celery_app:celery_app worker -Q resumes -l info
Beat (sweeper):      celery -A app.features.resumes.celery_app:celery_app beat -l info
If your project already has a Celery app, import `tasks` from it instead and drop this file.
"""

from __future__ import annotations

import socket
import threading
import time

from celery import Celery
from celery.signals import worker_ready

from .config import get_settings

_cfg = get_settings()

celery_app = Celery(
    "job_sentry_resumes",
    broker=_cfg.celery_broker_url,
    include=["app.ai_features.resumes.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,  # redeliver if a worker dies mid-task (pipeline is idempotent)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_send_task_events=False,
    task_send_sent_event=False,
    task_soft_time_limit=_cfg.task_soft_time_limit,
    task_time_limit=_cfg.task_soft_time_limit + 30,
    task_default_queue=_cfg.celery_queue,
    task_routes={
        "resumes.*": {"queue": _cfg.celery_queue},
        "candidate_intelligence.*": {"queue": _cfg.celery_queue},
    },
    broker_pool_limit=10,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 3600,
        "socket_timeout": 5,
        "socket_connect_timeout": 5,
        "retry_on_timeout": True,
    },
    beat_schedule={"resumes-requeue-stuck": {"task": "resumes.requeue_stuck", "schedule": 300.0}},
    timezone="UTC",
)


@worker_ready.connect
def _start_worker_heartbeat(sender=None, **kwargs) -> None:
    hostname = getattr(sender, "hostname", None) or f"celery@{socket.gethostname()}"

    def _heartbeat_loop() -> None:
        from redis import Redis

        client = Redis.from_url(_cfg.celery_broker_url, socket_connect_timeout=2, socket_timeout=2)
        while True:
            try:
                client.set(f"worker:heartbeat:{hostname}", "1", ex=45)
            except Exception:
                pass
            time.sleep(20)

    threading.Thread(target=_heartbeat_loop, name="worker-heartbeat", daemon=True).start()
