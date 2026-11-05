"""Normalize requirement weights to the 0-1 range.

Revision ID: 7a4d91c2e6b3
Revises: f2c3a01d84b7
Create Date: 2026-11-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7a4d91c2e6b3"
down_revision: Union[str, Sequence[str], None] = "f2c3a01d84b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE job_requirements SET weight = weight / 100.0")
    op.create_check_constraint(
        "ck_job_requirements_weight_range",
        "job_requirements",
        "weight >= 0 AND weight <= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_requirements_weight_range", "job_requirements", type_="check")
    op.execute("UPDATE job_requirements SET weight = weight * 100.0")
