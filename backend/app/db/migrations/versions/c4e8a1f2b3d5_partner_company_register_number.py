from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4e8a1f2b3d5"
down_revision: Union[str, Sequence[str], None] = "b7c1e2d4a9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "partners",
        sa.Column("company_register_number", sa.String(length=10), nullable=True),
    )
    op.create_unique_constraint(
        "uq_partners_organization_register",
        "partners",
        ["organization_id", "company_register_number"],
    )
    op.alter_column(
        "partners", "vat_number", existing_type=sa.String(length=20), nullable=True
    )
    op.create_check_constraint(
        "ck_partners_identifier",
        "partners",
        "vat_number IS NOT NULL OR company_register_number IS NOT NULL",
    )


def downgrade() -> None:
    """Downgrade schema.

    Partners that have only a company register number cannot exist without a VAT
    number in the old schema, so they are removed together with their checks.
    """
    op.execute(
        "DELETE FROM check_results WHERE partner_id IN "
        "(SELECT id FROM partners WHERE vat_number IS NULL)"
    )
    op.execute("DELETE FROM partners WHERE vat_number IS NULL")
    op.drop_constraint("ck_partners_identifier", "partners", type_="check")
    op.alter_column(
        "partners", "vat_number", existing_type=sa.String(length=20), nullable=False
    )
    op.drop_constraint("uq_partners_organization_register", "partners", type_="unique")
    op.drop_column("partners", "company_register_number")