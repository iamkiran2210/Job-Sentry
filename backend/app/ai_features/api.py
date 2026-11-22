"""One router for every AI-feature endpoint.  app.include_router(ai_features_router, prefix=<your API prefix>)"""

from __future__ import annotations

from fastapi import APIRouter

from .candidates.router import router as candidates_router
from .resumes.router import router as resumes_router

router = APIRouter()
router.include_router(
    resumes_router
)  # POST /jobs/{id}/resumes, GET /resumes/{id}[/status], POST /resumes/{id}/retry, GET /applications/{id}
router.include_router(candidates_router)  # GET /candidates/{id}
