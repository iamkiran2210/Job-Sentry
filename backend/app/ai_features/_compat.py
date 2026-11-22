"""
Seam between Phase 3 and the rest of the repo. If your Phase 1/2 names differ, this is the ONLY file to edit.
Everything marked ADAPT is taken from PROJECT_GUIDE.md and was not compiled against your real code.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

# ADAPT 1/4: auth + DB-session dependencies (guide: core/dependencies.py, core/database.py)
from app.core.database import get_db  # noqa: F401
from app.core.dependencies import get_current_active_user  # noqa: F401

# ADAPT 2/4: async DB URL. Celery workers have no request, so they build their own engine from it.
from app.core.config import settings as app_settings


def get_database_url() -> str:
    return str(app_settings.DATABASE_URL)


# ADAPT 3/4: response envelope (guide: utils/responses.py `success_response`)
from app.utils.responses import success_response


def ok(data: Any, message: str = "Success", status_code: int = 200) -> Response:
    body = success_response(data=jsonable_encoder(data), message=message)
    if isinstance(body, Response):  # helper already returns a Response
        body.status_code = status_code
        return body
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


# ADAPT 4/4: Phase 2 job access. JobsService.get_job already implements "company member OR explicit
# viewer/editor grant", raising your standard not-found / forbidden errors. We reuse it, never re-implement it.
from app.modules.jobs.service import JobsService


async def get_accessible_job(db, user, job_id, *, require_edit: bool = False):
    """Return the Job (with .company_id) or raise your normal 404/403. require_edit=True needs member or editor."""
    return await JobsService().get_job(db, user, job_id, require_edit=require_edit)


def is_access_denied(exc: BaseException) -> bool:
    """True for the 403/404 errors get_job raises (works for HTTPException and AppException-style classes)."""
    return getattr(exc, "status_code", None) in (403, 404)
