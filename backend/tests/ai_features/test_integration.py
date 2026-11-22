"""The 'drop-in' promise: one include_router + one models import is enough."""

import subprocess
import sys

from fastapi import FastAPI


def test_single_include_router_exposes_all_routes_and_openapi():
    from app.ai_features import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    spec = app.openapi()[
        "paths"
    ]  # what clients/Swagger see (this FastAPI no longer flattens app.routes)
    got = {(m.upper(), path) for path, ops in spec.items() for m in ops}
    assert got == {
        ("POST", "/api/v1/jobs/{job_id}/resumes"),
        ("GET", "/api/v1/resumes/{resume_id}"),
        ("DELETE", "/api/v1/resumes/{resume_id}"),
        ("GET", "/api/v1/resumes/{resume_id}/status"),
        ("POST", "/api/v1/resumes/{resume_id}/retry"),
        ("GET", "/api/v1/applications/{application_id}"),
        ("DELETE", "/api/v1/applications/{application_id}"),
        ("GET", "/api/v1/candidates/{candidate_id}"),
        ("PATCH", "/api/v1/candidates/{candidate_id}"),
        ("DELETE", "/api/v1/candidates/{candidate_id}"),
        ("DELETE", "/api/v1/candidates"),
        ("GET", "/api/v1/jobs/{job_id}/applicants"),
    }


def test_models_import_is_lightweight_and_registers_tables():
    code = (
        "import sys\n"
        "import app.ai_features.models\n"
        "assert 'app.ai_features.api' not in sys.modules, 'models import must not load the router'\n"
        "assert 'app.ai_features._compat' not in sys.modules\n"
        "from app.core.database import Base\n"
        "assert {'candidates','applications','resumes','extracted_profiles','identity_suggestions'} <= set(Base.metadata.tables)\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr[-600:]


def test_startup_check_reports_config(monkeypatch):
    from app.ai_features import startup_check
    from app.ai_features.ai.settings import get_ai_settings

    # Startup defaults should be tested regardless of local deployment settings.
    monkeypatch.setenv("AI_MODEL", "heuristic")
    monkeypatch.setenv("AI_ENGINE", "pydantic_ai")
    monkeypatch.setenv("AI_ENV", "development")
    monkeypatch.setenv("AI_FALLBACK_MODELS", " ")
    get_ai_settings.cache_clear()
    try:
        info = startup_check()
    finally:
        get_ai_settings.cache_clear()
    assert info["engine"] == "pydantic_ai" and info["offline"] is True


def test_exported_router_is_an_apirouter_regardless_of_import_order():
    """Regression: a submodule named `router` used to shadow the exported object."""
    code = (
        "import app.ai_features.api  # import the implementation module FIRST\n"
        "from app.ai_features import router\n"
        "from fastapi import APIRouter\n"
        "assert isinstance(router, APIRouter), type(router)\n"
        "from app.ai_features import router as again\n"
        "assert again is router\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr[-600:]
