#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  echo "alembic_test.sh: TEST_DATABASE_URL must be set to a disposable test database URL." >&2
  exit 2
fi

export ALEMBIC_TARGET=test
export ALEMBIC_DATABASE_URL="$TEST_DATABASE_URL"
exec uv run --project backend alembic -c backend/alembic.ini "$@"
