# Job Sentry

Job Sentry is an AI-powered recruitment intelligence platform.

## Architecture

- **Backend:** FastAPI, Python 3.12+, PostgreSQL, SQLAlchemy 2.0 Async, Alembic, Docker (`backend/`)
- **Frontend:** SvelteKit and TypeScript (planned in future phase)

## Current Status: Phase 2 In Progress

Phase 1 provides the core backend foundation:
- Database architecture & Alembic migrations
- User & Company models
- JWT dual-token authentication with Argon2 and persistent refresh token rotation
- Google OAuth integration
- Role-based authorization & strict company isolation
- Company-scoped job management and structured job requirements
- Admin-managed company membership and viewer/editor job sharing
- Recruiter-reviewed AI requirement extraction provider interface

For detailed instructions and documentation, see [`backend/README.md`](backend/README.md).

See the [Phase 2 brief](JOB_SENTRY_PHASE_2_BRIEF.md) for the job domain scope, API, lifecycle, and acceptance details.

See the [project guide](PROJECT_GUIDE.md) for the folder map, modules, classes, methods, and contributor notes.
