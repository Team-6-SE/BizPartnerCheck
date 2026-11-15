"""add organization VAT number

Revision ID: 281db6f412f8
Revises: e3d033729051
Create Date: 2026-11-15 15:15:38.161260

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '281db6f412f8'
down_revision: Union[str, Sequence[str], None] = '28c8865b2eef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'organizations',
        sa.Column('vat_number', sa.String(length=20), nullable=True)
    )
    op.create_unique_constraint(
        'uq_organizations_vat',
        'organizations',
        ['vat_number']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'uq_organizations_vat',
        'organizations',
        type_='unique'
    )
    op.drop_column('organizations', 'vat_number')
    # ### end Alembic commands ###
