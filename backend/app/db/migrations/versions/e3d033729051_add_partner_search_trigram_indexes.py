"""add partner search trigram indexes

Revision ID: e3d033729051
Revises: 1270515f4b21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e3d033729051"
down_revision: Union[str, Sequence[str], None] = "1270515f4b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add trigram indexes for partner substring searches."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_index(
        "ix_partners_company_name_trgm",
        "partners",
        ["company_name"],
        postgresql_using="gin",
        postgresql_ops={"company_name": "gin_trgm_ops"},
    )

    op.create_index(
        "ix_partners_vat_number_trgm",
        "partners",
        ["vat_number"],
        postgresql_using="gin",
        postgresql_ops={"vat_number": "gin_trgm_ops"},
    )

    op.create_index(
        "ix_partners_register_number_trgm",
        "partners",
        ["company_register_number"],
        postgresql_using="gin",
        postgresql_ops={"company_register_number": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Remove partner trigram indexes."""
    op.drop_index("ix_partners_register_number_trgm", table_name="partners")
    op.drop_index("ix_partners_vat_number_trgm", table_name="partners")
    op.drop_index("ix_partners_company_name_trgm", table_name="partners")