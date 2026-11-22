import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import Base
import app.ai_features.models  # noqa: F401 - register Phase 3 tables
import app.modules.candidate_intelligence.models  # noqa: F401 - register Phase 4 tables
from scripts.alembic_guard import enforce_database_target, resolve_database_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Select the explicit migration URL first; the app setting is only a fallback.
database_url = resolve_database_url(settings.DATABASE_URL)
offline_mode = context.is_offline_mode()
enforce_database_target(
    database_url,
    target=os.environ.get("ALEMBIC_TARGET"),
    confirmation=os.environ.get("ALEMBIC_CONFIRM_DB"),
    offline=offline_mode,
)
# Alembic's ConfigParser treats percent signs as interpolation markers.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_CANDIDATE_INTELLIGENCE_TABLES = {
    "verification_results",
    "candidate_scores",
    "score_evidence",
    "ranking_history",
}


def include_object(obj, name, type_, reflected, compare_to):
    """Limit Phase 4 drift checks to this module's tables."""
    if type_ == "table":
        return name in _CANDIDATE_INTELLIGENCE_TABLES
    if type_ == "index" and name == "ix_score_evidence_embedding_hnsw":
        # Created by c4 only when pgvector is installed; it is extension-specific.
        return False
    table = getattr(obj, "table", None)
    if table is None and compare_to is not None:
        table = getattr(compare_to, "table", None)
    return table is None or table.name in _CANDIDATE_INTELLIGENCE_TABLES


def compare_type(context_, inspected_column, metadata_column, inspected_type, metadata_type):
    """PostgreSQL's pgvector type is not reflected by SQLAlchemy's default inspector."""
    if metadata_column.table.name == "score_evidence" and metadata_column.name == "embedding":
        return False
    return None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS job_sentry"))
        connection.execute(text("SET search_path TO job_sentry, public"))
        connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=False,
        include_object=include_object,
        compare_type=compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connect_args = {}
    if "postgresql" in database_url:
        connect_args["server_settings"] = {"search_path": "job_sentry,public"}

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
