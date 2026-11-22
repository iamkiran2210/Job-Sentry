"""Add company membership management and job access grants.

Revision ID: 4c8d6f1a2e73
Revises: 7a4d91c2e6b3
Create Date: 2026-11-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4c8d6f1a2e73"
down_revision: Union[str, Sequence[str], None] = "7a4d91c2e6b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_access",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "access_level",
            sa.Enum("viewer", "editor", name="jobaccesslevel", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("granted_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["granted_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "user_id", name="uq_job_access_job_user"),
    )
    op.create_index(op.f("ix_job_access_id"), "job_access", ["id"], unique=False)
    op.create_index(op.f("ix_job_access_job_id"), "job_access", ["job_id"], unique=False)
    op.create_index(op.f("ix_job_access_user_id"), "job_access", ["user_id"], unique=False)
    op.create_index("ix_job_access_user_job", "job_access", ["user_id", "job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_access_user_job", table_name="job_access")
    op.drop_index(op.f("ix_job_access_user_id"), table_name="job_access")
    op.drop_index(op.f("ix_job_access_job_id"), table_name="job_access")
    op.drop_index(op.f("ix_job_access_id"), table_name="job_access")
    op.drop_table("job_access")
