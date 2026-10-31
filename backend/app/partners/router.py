import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Partner
from app.db.session import get_db
from app.errors import api_error
from app.partners.vat import InvalidVatNumber, validate_vat_number
from app.tenancy import get_current_organization_id

router = APIRouter(prefix="/partners", tags=["partners"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]

UNIQUE_VAT_CONSTRAINT = "uq_partners_organization_vat"


class PartnerCreate(BaseModel):
    vat_number: str


class PartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vat_number: str
    created_at: datetime


def _duplicate(vat_number: str) -> HTTPException:
    return api_error(
        status.HTTP_409_CONFLICT,
        "duplicate_partner",
        f"A partner with VAT number {vat_number} already exists.",
        field="vat_number",
    )


@router.post("", response_model=PartnerRead, status_code=status.HTTP_201_CREATED)
def create_partner(
    body: PartnerCreate, db: DbSession, organization_id: OrganizationId
) -> Partner:
    try:
        vat_number = validate_vat_number(body.vat_number)
    except InvalidVatNumber as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_vat_format",
            str(exc),
            field="vat_number",
        ) from exc

    existing = db.scalar(
        select(Partner.id).where(
            Partner.organization_id == organization_id,
            Partner.vat_number == vat_number,
        )
    )
    if existing is not None:
        raise _duplicate(vat_number)

    partner = Partner(organization_id=organization_id, vat_number=vat_number)
    db.add(partner)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Two requests at the same time: the unique constraint catches the second one.
        # Any other integrity problem is a real error and must not look like a duplicate.
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == UNIQUE_VAT_CONSTRAINT:
            raise _duplicate(vat_number) from exc
        raise
    db.refresh(partner)
    return partner


@router.get("", response_model=list[PartnerRead])
def list_partners(db: DbSession, organization_id: OrganizationId) -> list[Partner]:
    return list(
        db.scalars(
            select(Partner)
            .where(Partner.organization_id == organization_id)
            .order_by(Partner.created_at.desc(), Partner.id)
        )
    )
