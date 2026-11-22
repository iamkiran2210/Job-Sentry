# Integration Findings — Phase 4

1. **Layout and plug-in pattern.** The backend is a FastAPI app under `backend/app`. Phase 1 domains live in
   `app/modules/{auth,companies,jobs,users}`; Phase 3 is an `app/ai_features` sidecar with its own API/router and
   subpackages (`resumes`, `candidates`, `ai`, `models`). `app.main` explicitly includes routers, and
   `app.ai_features.models` imports its tables so they share `app.core.database.Base.metadata`. Candidate intelligence
   follows the modular `app/modules/candidate_intelligence` convention already scaffolded here and is registered
   explicitly.
2. **Database.** SQLAlchemy 2 async ORM, `AsyncSession`, and declarative `Base` are in `app/core/database.py`;
   UUID/timestamp base is `app/models/base.py` (`BaseModel`). Tables use snake_case plural names, UUID PKs, UTC
   timestamps, named constraints/indexes, PostgreSQL JSONB with SQLite JSON fallback. Alembic's active chain is under
   `backend/migrations`; the Phase 4 head is `d6f3a810bc42`, verified against the configured PostgreSQL database. The
   server does not provide pgvector, so the Phase 4 migration uses JSONB embedding storage there; vector storage and
   HNSW indexing are enabled when the extension is installed. SQLite remains the unit-test DB.
3. **Existing models reused.** `Application`, `Candidate`, `Resume`, and `ExtractedProfile` live under
   `app.ai_features.models`; `Job`, `JobRequirement`, `Company`, and `User`/`UserRole` live under `app.models`. The
   profile's `profile_data` JSON is validated Phase 3 `ExtractedProfileData`: contact claims/URLs, summary, skills,
   employment, experience claims, education, certifications, and projects. Resume original-file SHA-256 is on
   `Resume.sha256`; extracted source text is `ExtractedProfile.source_text`. No parallel copies should be introduced.
4. **Authorization and tenancy.** Auth routes use `get_current_active_user`. `JobsService.get_job` is the Phase 2 access
   seam: company members have access; explicit `JobAccess` grants allow job viewers/editors; viewer grants cannot edit.
   Phase 3 candidate routes use their compatibility seam and hide unauthorized entities as not found. Intelligence
   routes must first scope application by ID then authorize its job through `JobsService.get_job`; verification and
   analysis are job-scoped. Company IDs are attached to candidate/resume/application records.
5. **Configuration and services.** Global settings are Pydantic Settings in `app/core/config.py`, loaded from `.env`;
   module-specific settings use prefixed Pydantic settings (the existing candidate-intelligence scaffold uses
   `INTELLIGENCE_`). DB injection is `Depends(get_db)`. Errors use `AppException` subclasses and response JSON is
   `{success,message,data,errors}` via `success_response`. Logging uses named standard-library loggers. Resume ingestion
   uses Celery/Redis with optional inline dispatch (`ai_features/resumes`); it is the background-task pattern. Existing
   structured extraction uses Pydantic AI, with a separate DSPy requirement engine. Phase 4 will use provider protocols
   and settings-driven factories, with deterministic mock defaults.
6. **Tests.** Pytest + pytest-asyncio, async FastAPI `AsyncClient`, per-test SQLAlchemy metadata creation, and SQLite
   in-memory/`StaticPool` are configured in `backend/tests/conftest.py`. Existing AI tests use injectable/mock providers
   and no network by default. `backend/pyproject.toml` declares no lint/type tool configuration, and required CLI tools
   are not necessarily installed.
7. **Requirement/profile shape.** Phase 2 stores each requirement as
   `JobRequirement(category,name,requirement_type,importance,weight,is_mandatory)`; normalized categories include
   skills, experience, education, certification, language, responsibility, other. Phase 3 stores grounded, unverified
   claims in `ExtractedProfile.profile_data`; no new extraction fields are needed. The candidate model's name/contact
   values and profile contact/location/identity fields are explicitly excluded from evidence/scoring.

## Phase 4 extension decisions

- Add new tables only for verification results, scores, evidence, and immutable ranking runs. Scores are version-unique
  per application; ranking history is append-only.
- Store embedding vectors using PostgreSQL's `vector` type when available; on SQLite use a JSON-compatible fallback for
  unit tests. PostgreSQL migration enables `vector` only if the server supports the extension. The Alembic environment
  currently has `target_metadata = None`; the migration is explicit and does not depend on autogeneration.
- No existing ranking cursor/background queue contract is present. The API is synchronous and idempotent for one call;
  the existing Celery resume queue remains the only optional background mechanism. Bulk-ranking can be queued in a
  future extension without changing pure layers.
- Verification statuses mean: `passed` = deterministic format/consistency check passed; `needs_review` = a non-failing
  anomaly/signal needs human review; `not_verified` = absent input or check unavailable/disabled; `failed` = input is
  present and demonstrably invalid. These signals do not prove identity, employment, or skill.
