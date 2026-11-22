from __future__ import annotations

import io

import pytest
from scripts.alembic_guard import enforce_database_target, resolve_database_url

SECRET_URL = "postgresql+asyncpg://phaseuser:super-secret@db.internal:5432/application"
TEST_URL = "postgresql+asyncpg://phaseuser:super-secret@db.internal:5432/job_sentry_test"


def test_non_test_database_without_confirmation_exits_and_masks_password():
    output = io.StringIO()
    with pytest.raises(SystemExit) as error:
        enforce_database_target(SECRET_URL, stream=output)
    assert error.value.code == 2
    assert "host=db.internal database=application" in output.getvalue()
    assert "super-secret" not in output.getvalue()
    assert "phaseuser" not in output.getvalue()


def test_test_database_is_allowed_for_online_operation():
    enforce_database_target(TEST_URL, target="test")


def test_non_test_database_requires_exact_confirmation():
    enforce_database_target(SECRET_URL, confirmation="application")


def test_test_target_rejects_non_test_database_even_with_confirmation():
    output = io.StringIO()
    with pytest.raises(SystemExit) as error:
        enforce_database_target(
            SECRET_URL, target="test", confirmation="application", stream=output
        )
    assert error.value.code == 2
    assert "super-secret" not in output.getvalue()


def test_offline_sql_generation_is_allowed_without_database_confirmation():
    enforce_database_target(SECRET_URL, offline=True)


def test_explicit_alembic_url_takes_precedence_over_app_setting():
    assert (
            resolve_database_url("postgresql://app/appdb", {"ALEMBIC_DATABASE_URL": TEST_URL})
            == TEST_URL
    )
    assert resolve_database_url("postgresql://app/appdb", {}) == "postgresql://app/appdb"
