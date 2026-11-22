"""Test helpers. make_company / make_user / make_job fill every required column of YOUR models automatically."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import sqlalchemy as sa

from app.core.database import Base

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.models.company import Company
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.identity_suggestion import IdentitySuggestion
from app.models.job import Job
from app.ai_features.models.resume import Resume
from app.models.user import User
from app.ai_features.resumes.errors import DispatchError
from app.ai_features.resumes.llm import LLMResult
from app.ai_features.resumes.pipeline import process_resume
from app.ai_features.resumes.service import ResumesService

__all__ = [
    "Application",
    "Candidate",
    "ExtractedProfile",
    "IdentitySuggestion",
    "Resume",
]


# ------------------------------------------------------------------ row factories (work with YOUR real models)
def _dummy(col, n: int):
    """A valid-looking value for a required column, chosen by its SQL type."""
    t = col.type
    if isinstance(t, sa.Enum):
        return next(iter(t.enum_class)) if t.enum_class else t.enums[0]
    if isinstance(t, sa.Boolean):
        return True
    if isinstance(t, sa.Integer):
        return 1
    if isinstance(t, (sa.Float, sa.Numeric)):
        return 1
    if isinstance(t, sa.DateTime):
        return datetime.now(timezone.utc)
    if isinstance(t, sa.Date):
        return date.today()
    if isinstance(t, sa.Uuid):
        return uuid.uuid4()
    if isinstance(t, sa.JSON):
        return {}
    if isinstance(t, sa.ARRAY):
        return []
    if isinstance(t, (sa.String, sa.Text)):
        text = f"test-{uuid.uuid4().hex[:10]}" if col.unique else f"test {col.name} {n}"
        return text[: t.length] if getattr(t, "length", None) else text
    return None


async def _make(factory, model, depth: int = 0, **given):
    """Insert one `model` row. Required columns you don't pass are filled automatically, and a required
    foreign key creates its parent row first, so this keeps working when your models gain required fields."""
    registry = {
        m.class_.__table__.name: m.class_
        for m in Base.registry.mappers
        if hasattr(m.class_, "__table__")
    }
    values = dict(given)
    for col in model.__table__.columns:
        if (
                col.key in values
                or col.primary_key
                or col.nullable
                or col.default is not None
                or col.server_default is not None
        ):
            continue
        if col.foreign_keys:
            fk = next(iter(col.foreign_keys))
            parent = registry.get(fk.column.table.name)
            if parent is None or depth >= 3:
                raise RuntimeError(
                    f"cannot auto-create parent for {model.__tablename__}.{col.name}; pass it explicitly"
                )
            values[col.key] = getattr(await _make_obj(factory, parent, depth + 1), fk.column.key)
        else:
            values[col.key] = _dummy(col, depth)
    async with factory() as s:
        obj = model(**values)
        s.add(obj)
        await s.commit()
        await s.refresh(obj)
        return obj


_make_obj = _make


async def make_company(factory, name="Acme") -> uuid.UUID:
    return (await _make(factory, Company, name=name)).id


async def make_user(factory, company_id=None, email=None) -> SimpleNamespace:
    obj = await _make(
        factory,
        User,
        email=email or f"u{uuid.uuid4().hex[:8]}@example.com",
        company_id=company_id,
    )
    return SimpleNamespace(id=obj.id, company_id=company_id)


async def make_job(factory, company_id) -> uuid.UUID:
    return (await _make(factory, Job, company_id=company_id, title="Engineer")).id


# ------------------------------------------------------------------ fakes
class FakeLLM:
    """Scripted provider. Each item is a dict (success) or an Exception to raise."""

    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    async def extract_profile(self, *, resume_text: str) -> LLMResult:
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return LLMResult(data=item, provider="fake", model="fake-1", prompt_version="test-v1")


class RecordingDispatcher:
    def __init__(self, fail=False):
        self.ids, self.fail = [], fail

    def enqueue(self, resume_id):
        if self.fail:
            raise DispatchError("down")
        self.ids.append(resume_id)


# ------------------------------------------------------------------ actions
async def upload(
        factory,
        cfg,
        storage,
        company,
        job_id,
        data,
        name="cv.pdf",
        dispatcher=None,
        user=None,
):
    job = SimpleNamespace(id=job_id, company_id=company)
    user = user or SimpleNamespace(id=None, company_id=company)
    async with factory() as s:
        return await ResumesService.ingest_file(
            s,
            job=job,
            user=user,
            filename=name,
            data=data,
            cfg=cfg,
            storage=storage,
            dispatcher=dispatcher or RecordingDispatcher(),
        )


async def run(factory, cfg, storage, llm, resume_id, ocr=None):
    return await process_resume(
        resume_id, session_factory=factory, storage=storage, llm=llm, cfg=cfg, ocr=ocr
    )


async def count(factory, model, **where):
    async with factory() as s:
        q = sa.select(sa.func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return (await s.execute(q)).scalar_one()


async def row(factory, model, id_):
    async with factory() as s:
        return await s.get(model, id_)
