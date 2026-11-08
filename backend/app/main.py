from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.observability import SecurityHeadersMiddleware, StructuredRequestLoggingMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.companies.router import router as companies_router
from app.modules.jobs.router import router as jobs_router
from app.modules.users.router import router as users_router
from app.modules.candidate_intelligence.api.router import router as candidate_intelligence_router
from app.modules.application_status.router import router as application_status_router
from app.modules.analytics.router import router as analytics_router
from app.modules.health.router import router as health_router

from app.ai_features import startup_check
from app.ai_features.api import router as ai_features_router
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for managing startup and shutdown."""

    startup_check()
    # Startup: connection verification
    yield
    # Shutdown: clean up database connections
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Job Sentry Backend API - Foundation, Organizations & Recruitment Job Domain",
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
    lifespan=lifespan,
)
app.add_middleware(StructuredRequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# CORS Middleware
origins = settings.ALLOWED_CORS_ORIGINS
if isinstance(origins, str):
    origins = [origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Register Routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(users_router, prefix=settings.API_V1_PREFIX)
app.include_router(companies_router, prefix=settings.API_V1_PREFIX)
app.include_router(jobs_router, prefix=settings.API_V1_PREFIX)
app.include_router(ai_features_router, prefix=settings.API_V1_PREFIX)
app.include_router(candidate_intelligence_router, prefix=settings.API_V1_PREFIX)
app.include_router(application_status_router, prefix=settings.API_V1_PREFIX)
app.include_router(analytics_router, prefix=settings.API_V1_PREFIX)
app.include_router(health_router)
