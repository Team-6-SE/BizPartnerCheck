"""common check result format for all sources

Statuses become the same for every source: OK, FINDING, REVIEW, NOT_APPLICABLE, ERROR
(status column widened to 20 characters for NOT_APPLICABLE).
Existing VIES rows are renamed: VALID -> OK, INVALID -> FINDING.
New columns: explanation (text shown at the time) and data_as_of (age of imported data).

Revision ID: b7c1e2d4a9f0
Revises: f90a185a4670
Create Date: 2026-11-09 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c1e2d4a9f0"
down_revision: Union[str, Sequence[str], None] = "f90a185a4670"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_check_results_status"


def upgrade() -> None:
    op.add_column("check_results", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column(
        "check_results",
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(CONSTRAINT, "check_results", type_="check")
    op.alter_column(
        "check_results",
        "status",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.execute(
        "UPDATE check_results SET status = CASE status"
        " WHEN 'VALID' THEN 'OK' WHEN 'INVALID' THEN 'FINDING' ELSE status END"
    )
    op.create_check_constraint(
        CONSTRAINT,
        "check_results",
        "status IN ('OK', 'FINDING', 'REVIEW', 'NOT_APPLICABLE', 'ERROR')",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "check_results", type_="check")
    # REVIEW and NOT_APPLICABLE did not exist before; "not confirmed" (ERROR) is the
    # safe old meaning.
    op.execute(
        "UPDATE check_results SET status = CASE status"
        " WHEN 'OK' THEN 'VALID' WHEN 'FINDING' THEN 'INVALID'"
        " WHEN 'REVIEW' THEN 'ERROR' WHEN 'NOT_APPLICABLE' THEN 'ERROR' ELSE status END"
    )
    op.alter_column(
        "check_results",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
    op.create_check_constraint(
        CONSTRAINT, "check_results", "status IN ('VALID', 'INVALID', 'ERROR')"
    )
    op.drop_column("check_results", "data_as_of")
    op.drop_column("check_results", "explanation")
