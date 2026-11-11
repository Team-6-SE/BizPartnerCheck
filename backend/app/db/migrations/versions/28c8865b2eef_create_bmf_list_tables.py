"""create bmf list tables

Revision ID: 28c8865b2eef
Revises: c4e8a1f2b3d5
Create Date: 2026-11-09 19:30:39.063012

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28c8865b2eef'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1f2b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """BMF fake-company list (local copy) and the history of its imports."""
    op.create_table('bmf_imports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('started_by', sa.String(length=320), nullable=True),
    sa.Column('entries_in_feed', sa.Integer(), nullable=True),
    sa.Column('entries_added', sa.Integer(), nullable=True),
    sa.Column('entries_removed', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('SUCCESS', 'FAILED')", name='ck_bmf_imports_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bmf_imports_status_finished_at', 'bmf_imports', ['status', 'finished_at'], unique=False)
    op.create_table('bmf_list_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('entry_key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('normalized_name', sa.Text(), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('vat_number', sa.String(length=20), nullable=True),
    sa.Column('ur_number', sa.String(length=20), nullable=True),
    sa.Column('register_number', sa.String(length=20), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('published_on', sa.Date(), nullable=False),
    sa.Column('fake_since', sa.Date(), nullable=True),
    sa.Column('decision_final_on', sa.Date(), nullable=True),
    sa.Column('link', sa.Text(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entry_key')
    )
    op.create_index(op.f('ix_bmf_list_entries_normalized_name'), 'bmf_list_entries', ['normalized_name'], unique=False)
    op.create_index(op.f('ix_bmf_list_entries_register_number'), 'bmf_list_entries', ['register_number'], unique=False)
    op.create_index(op.f('ix_bmf_list_entries_ur_number'), 'bmf_list_entries', ['ur_number'], unique=False)
    op.create_index(op.f('ix_bmf_list_entries_vat_number'), 'bmf_list_entries', ['vat_number'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bmf_list_entries_vat_number'), table_name='bmf_list_entries')
    op.drop_index(op.f('ix_bmf_list_entries_ur_number'), table_name='bmf_list_entries')
    op.drop_index(op.f('ix_bmf_list_entries_register_number'), table_name='bmf_list_entries')
    op.drop_index(op.f('ix_bmf_list_entries_normalized_name'), table_name='bmf_list_entries')
    op.drop_table('bmf_list_entries')
    op.drop_index('ix_bmf_imports_status_finished_at', table_name='bmf_imports')
    op.drop_table('bmf_imports')
