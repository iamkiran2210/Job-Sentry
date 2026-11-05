# Job Sentry

Job Sentry is an AI-powered recruitment intelligence platform.

## Architecture

- **Backend:** FastAPI, Python 3.12+, PostgreSQL, SQLAlchemy 2.0 Async, Alembic, Docker (`backend/`)
- **Frontend:** SvelteKit and TypeScript (planned in future phase)

## Current Status: Phase 1 Completed

Phase 1 provides the core backend foundation:
- Database architecture & Alembic migrations
- User & Company models
- JWT dual-token authentication with Argon2 and persistent refresh token rotation
- Google OAuth integration
- Role-based authorization & strict company isolation
- 100% automated test suite passing

For detailed instructions and documentation, see [`backend/README.md`](backend/README.md).
