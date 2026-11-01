import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Partner(Base):
    __tablename__ = "partners"
    __table_args__ = (
        # The same VAT number may exist only once per organization (tenant).
        UniqueConstraint(
            "organization_id", "vat_number", name="uq_partners_organization_vat"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    # Stored normalised: upper case, no spaces, e.g. "ATU12345678".
    vat_number: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CheckResult(Base):
    """One check of a partner against one source (e.g. VIES).

    A new row is added for every check; old rows are never changed, so the history
    shows what a source said at which time.
    """

    __tablename__ = "check_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('VALID', 'INVALID', 'ERROR')", name="ck_check_results_status"
        ),
        # Fast lookup of the latest result per partner.
        Index("ix_check_results_partner_checked_at", "partner_id", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partners.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    # Set by the app (not now() in the database), so two checks in one
    # transaction still get different times.
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    # The answer of the source exactly as received (or what went wrong).
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
