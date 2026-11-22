from __future__ import annotations

import asyncio
import logging
import uuid

from celery.signals import worker_process_init, worker_process_shutdown
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai_features._compat import get_database_url
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.explanations import (
    PydanticAIExplanationGenerator,
    generate_and_store_explanation,
)
from .celery_app import celery_app
from .config import get_settings
from .llm import get_llm_provider
from .pipeline import Outcome, process_resume
from .service import find_stuck_resume_ids
from .storage import get_storage

log = logging.getLogger("resumes.tasks")

_WORKER_LOOP: asyncio.AbstractEventLoop | None = None
_WORKER_ENGINE: AsyncEngine | None = None
_WORKER_DB_URL: str | None = None
_WORKER_SESSION_FACTORY: async_sessionmaker | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _WORKER_LOOP
    if _WORKER_LOOP is None or _WORKER_LOOP.is_closed():
        _WORKER_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_WORKER_LOOP)
    return _WORKER_LOOP


def _get_worker_session_factory() -> async_sessionmaker:
    """Reuse one pooled AsyncEngine per Celery worker process instead of reconnecting 5x per resume."""
    global _WORKER_ENGINE, _WORKER_DB_URL, _WORKER_SESSION_FACTORY
    url = get_database_url()
    if _WORKER_ENGINE is not None and _WORKER_DB_URL == url and _WORKER_SESSION_FACTORY is not None:
        return _WORKER_SESSION_FACTORY
    if _WORKER_ENGINE is not None:
        try:
            _get_worker_loop().run_until_complete(_WORKER_ENGINE.dispose())
        except Exception:
            pass
    if "postgresql" in url:
        _WORKER_ENGINE = create_async_engine(
            url,
            pool_size=3,
            max_overflow=3,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={"server_settings": {"search_path": "job_sentry,public"}},
        )
    else:
        _WORKER_ENGINE = create_async_engine(url, poolclass=NullPool)
    _WORKER_DB_URL = url
    _WORKER_SESSION_FACTORY = async_sessionmaker(_WORKER_ENGINE, expire_on_commit=False)
    return _WORKER_SESSION_FACTORY


@worker_process_init.connect
def _reset_worker_runtime(**kwargs) -> None:
    """Ensure forked Celery workers never inherit parent event loops or DB sockets."""
    global _WORKER_LOOP, _WORKER_ENGINE, _WORKER_DB_URL, _WORKER_SESSION_FACTORY
    _WORKER_LOOP = None
    _WORKER_ENGINE = None
    _WORKER_DB_URL = None
    _WORKER_SESSION_FACTORY = None


@worker_process_shutdown.connect
def _shutdown_worker_runtime(**kwargs) -> None:
    global _WORKER_LOOP, _WORKER_ENGINE, _WORKER_DB_URL, _WORKER_SESSION_FACTORY
    if _WORKER_ENGINE is not None and _WORKER_LOOP is not None and not _WORKER_LOOP.is_closed():
        try:
            _WORKER_LOOP.run_until_complete(_WORKER_ENGINE.dispose())
        except Exception:
            pass
    if _WORKER_LOOP is not None and not _WORKER_LOOP.is_closed():
        try:
            _WORKER_LOOP.close()
        except Exception:
            pass
    _WORKER_LOOP = None
    _WORKER_ENGINE = None
    _WORKER_DB_URL = None
    _WORKER_SESSION_FACTORY = None


def _run(coro_factory):
    """Run an async coroutine on this worker process's persistent event loop and pooled engine."""
    loop = _get_worker_loop()
    factory = _get_worker_session_factory()
    return loop.run_until_complete(coro_factory(factory))


def run_pipeline_sync(resume_id: uuid.UUID) -> Outcome:
    cfg = get_settings()
    return _run(
        lambda f: process_resume(
            resume_id,
            session_factory=f,
            storage=get_storage(),
            llm=get_llm_provider(),
            cfg=cfg,
        )
    )


@celery_app.task(
    bind=True, name="resumes.process_resume", acks_late=True, reject_on_worker_lost=True
)
def process_resume_task(self, resume_id: str) -> str:
    outcome = run_pipeline_sync(uuid.UUID(resume_id))
    if outcome.kind == "retry":
        # attempt accounting lives in the DB; Celery's own cap is just a safety net
        raise self.retry(
            countdown=outcome.retry_in, max_retries=get_settings().task_max_attempts + 2
        )
    return outcome.kind


async def _generate_explanation(session_factory, score_id: uuid.UUID) -> str:
    from app.ai_features.ai.settings import get_ai_settings

    cfg = get_intelligence_settings()
    ai_cfg = get_ai_settings()
    model = cfg.llm_model
    if (not model or model in {"heuristic", "test"}) and not ai_cfg.offline:
        model = ai_cfg.model
    if not model or model in {"heuristic", "test"}:
        return "skipped_offline_model"
    async with session_factory() as session:
        record = await generate_and_store_explanation(
            session,
            score_id,
            PydanticAIExplanationGenerator(model, cfg.llm_timeout_seconds),
            generator_model=model,
            prompt_version="score-explanation-v4",
        )
        await session.commit()
        return record.status if record else "score_not_found"


@celery_app.task(
    name="candidate_intelligence.generate_score_explanation",
    acks_late=True,
)
def generate_score_explanation_task(score_id: str) -> str:
    """Generate an evidence-cited explanation in a worker, never during GET."""
    return _run(lambda factory: _generate_explanation(factory, uuid.UUID(score_id)))


@celery_app.task(name="resumes.requeue_stuck")
def requeue_stuck() -> int:
    """Re-enqueue resumes whose message was lost (broker outage, crashed worker). Safe: pipeline is idempotent."""
    cfg = get_settings()
    ids = _run(lambda f: find_stuck_resume_ids(f, cfg))
    for rid in ids:
        process_resume_task.apply_async(args=[str(rid)], queue=cfg.celery_queue)
    return len(ids)
