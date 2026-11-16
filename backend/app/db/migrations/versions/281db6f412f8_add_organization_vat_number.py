"""add unique organization VAT number

Revision ID: 281db6f412f8
Revises: c2f8e86d1823
Create Date: 2026-11-15 15:15:38.161260

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '281db6f412f8'
down_revision: Union[str, Sequence[str], None] = 'c2f8e86d1823'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
    # ### end Alembic commands ###
