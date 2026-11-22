# Backend architecture

This document describes the current backend layout and the dependency direction for Phase 5. It does not imply that
every target layer already has a dedicated package.

## Layers

| Layer        | Current location                                                                                                         | Responsibility                                                                                                                                                |
|--------------|--------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| API          | `app/modules/*/router.py`, `app/modules/candidate_intelligence/api/`, `app/ai_features/*/router.py`                      | HTTP routes, authentication dependencies, request/response schemas, and HTTP-to-service error mapping.                                                        |
| Services     | `app/modules/*/service.py`, `app/modules/candidate_intelligence/service.py`, `app/ai_features/*/service.py`              | Use-case orchestration, authorization checks through shared services, transactions, and calls into repositories/domain logic.                                 |
| Domain       | `app/modules/candidate_intelligence/scoring/`, `verification/`, `matching/`, `ranking/`; AI extraction/grounding helpers | Pure scoring, ranking, verification and extraction rules. Domain functions should not import FastAPI, SQLAlchemy sessions, storage clients, or provider SDKs. |
| Repositories | Currently expressed as SQLAlchemy statements in service modules                                                          | Persistence queries and writes. Extract a repository only when it creates a clear boundary or removes duplicated query logic.                                 |
| Database     | `app/models/`, module `models.py`, `migrations/versions/`                                                                | SQLAlchemy models, constraints, indexes and Alembic history. `app/core/database.py` owns engine/session setup.                                                |
| Workers      | `app/ai_features/resumes/tasks.py`, `pipeline.py`, `celery_app.py`                                                       | Background resume processing and retry/lease behavior. Phase 5 async work belongs here when it must not run in a request.                                     |
| Core         | `app/core/`                                                                                                              | Typed settings, database/session construction, auth dependencies, security primitives, shared errors and cross-cutting logging.                               |
| Schemas      | `app/schemas/`, `app/modules/candidate_intelligence/schemas.py`, `app/ai_features/schemas/`                              | Validate public input and shape public output. Schemas must exclude protected attributes and internal storage/provider details.                               |

## Dependency direction

The intended direction is:

```text
API routers and schemas -> services -> repositories -> database models
                         -> domain functions
workers -> services / domain / repositories
domain -> standard library and small immutable value types only
core -> framework adapters and infrastructure setup; feature modules consume core interfaces
```

Routers should not contain scoring or query policy. Services coordinate use cases but should call pure domain functions
for calculations. Domain code must not import FastAPI, SQLAlchemy, Celery, Redis, storage, or external model clients.
Provider, storage, mail, and explanation integrations are supplied through protocols at the service/worker boundary.
Database models and migrations do not depend on routers or services.

## Current modules

- `auth`: login, refresh-token lifecycle and current-user dependencies.
- `companies`: company and membership operations.
- `jobs`: job CRUD, requirements, job access and provider integration.
- `users`: user profile and account operations.
- `candidate_intelligence`: verification, matching evidence, scoring, analysis and ranking history.
- `ai_features`: resume intake, storage, parsing, extraction, candidate associations and Celery workers. This tree is
  present in the worktree but is not fully tracked in the current Git baseline; treat it as a separate integration
  boundary until its ownership is settled.
- `core`, `models`, `schemas`, and `utils`: shared framework setup, persistence models, request/response types and small
  cross-module helpers.

## Target tree

Keep the present feature-module layout unless a dependency violation requires a move:

```text
app/
  api/                         # optional top-level API composition as route count grows
  core/                        # settings, logging, security, errors, middleware, database
  models/                      # shared SQLAlchemy models
  schemas/                     # shared public schemas
  modules/
    auth/{api,services,domain,repositories}/
    companies/{api,services,domain,repositories}/
    jobs/{api,services,domain,repositories}/
    users/{api,services,domain,repositories}/
    candidate_intelligence/{api,services,domain,repositories,models}/
  workers/                     # Celery app, task registration and health
  ai_features/                 # resume pipeline integration, subject to ownership/track review
migrations/versions/
tests/                         # unit, integration, security, e2e
docs/
```

The target subpackages are a direction for new code, not a mandate to move existing files. F1 only moves a file when its
current location violates the dependency direction and a tested move reduces coupling.
