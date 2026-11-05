"""Allow decimal scoring weights on job requirements.

Revision ID: f2c3a01d84b7
Revises: 9b1c4f6e2a71
Create Date: 2026-11-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2c3a01d84b7"
down_revision: Union[str, Sequence[str], None] = "9b1c4f6e2a71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "job_requirements",
        "weight",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "job_requirements",
        "weight",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
