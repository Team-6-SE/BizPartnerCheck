"""create check_runs table and link check results to a run (S5.1)

Revision ID: a6c3f1e2b9d4
Revises: 281db6f412f8
Create Date: 2026-11-19 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a6c3f1e2b9d4'
down_revision: Union[str, Sequence[str], None] = '281db6f412f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'check_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=False),
        sa.Column('partner_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('started_by', sa.String(length=64), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'complete', 'incomplete')",
            name='ck_check_runs_status',
        ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['partner_id'], ['partners.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_check_runs_partner_started_at', 'check_runs', ['partner_id', 'started_at']
    )
    op.create_index(
        'ix_check_runs_organization_started_at',
        'check_runs',
        ['organization_id', 'started_at'],
    )
    op.create_index('ix_check_runs_status', 'check_runs', ['status'])

    # Results made before runs existed keep run_id empty.
    op.add_column('check_results', sa.Column('run_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_check_results_run_id', 'check_results', 'check_runs', ['run_id'], ['id']
    )
    op.create_index('ix_check_results_run_id', 'check_results', ['run_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_check_results_run_id', table_name='check_results')
    op.drop_constraint('fk_check_results_run_id', 'check_results', type_='foreignkey')
    op.drop_column('check_results', 'run_id')
    op.drop_index('ix_check_runs_status', table_name='check_runs')
    op.drop_index('ix_check_runs_organization_started_at', table_name='check_runs')
    op.drop_index('ix_check_runs_partner_started_at', table_name='check_runs')
    op.drop_table('check_runs')
