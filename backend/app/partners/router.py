import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import vies
from app.adapters.vies import CheckStatus, ViesAdapter, get_vies_adapter
from app.db.models import CheckResult, Partner
from app.db.session import get_db
from app.errors import api_error
from app.partners.vat import InvalidVatNumber, validate_vat_number
from app.tenancy import get_current_organization_id

router = APIRouter(prefix="/partners", tags=["partners"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
Vies = Annotated[ViesAdapter, Depends(get_vies_adapter)]

UNIQUE_VAT_CONSTRAINT = "uq_partners_organization_vat"


class PartnerCreate(BaseModel):
    vat_number: str


class CheckRead(BaseModel):
    id: uuid.UUID
    source: str
    status: CheckStatus
    checked_at: datetime
    # Explanation for people, e.g. why the check gave ERROR.
    message: str
    # Registered name from VIES, if the country shares it.
    company_name: str | None

    @classmethod
    def from_result(cls, result: CheckResult) -> "CheckRead":
        status_ = CheckStatus(result.status)
        return cls(
            id=result.id,
            source=result.source,
            status=status_,
            checked_at=result.checked_at,
            message=vies.describe(status_, result.raw_response),
            company_name=(
                vies.company_name(result.raw_response)
                if status_ == CheckStatus.VALID
                else None
            ),
        )


class PartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vat_number: str
    created_at: datetime
    latest_vies_check: CheckRead | None = None


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
def list_partners(db: DbSession, organization_id: OrganizationId) -> list[PartnerRead]:
    partners = db.scalars(
        select(Partner)
        .where(Partner.organization_id == organization_id)
        .order_by(Partner.created_at.desc(), Partner.id)
    ).all()

    # Latest VIES result per partner (PostgreSQL DISTINCT ON), one query for all.
    latest = db.scalars(
        select(CheckResult)
        .join(Partner, CheckResult.partner_id == Partner.id)
        .where(
            Partner.organization_id == organization_id,
            CheckResult.source == vies.SOURCE,
        )
        .order_by(
            CheckResult.partner_id,
            CheckResult.checked_at.desc(),
            CheckResult.id.desc(),
        )
        .ext(distinct_on(CheckResult.partner_id))
    ).all()
    latest_by_partner = {result.partner_id: result for result in latest}

    return [
        PartnerRead(
            id=partner.id,
            vat_number=partner.vat_number,
            created_at=partner.created_at,
            latest_vies_check=(
                CheckRead.from_result(latest_by_partner[partner.id])
                if partner.id in latest_by_partner
                else None
            ),
        )
        for partner in partners
    ]


@router.post(
    "/{partner_id}/checks/vies",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "Partner not found"}},
)
def run_vies_check(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
    adapter: Vies,
) -> CheckRead:
    """Ask VIES now and store the answer.

    The result is VALID, INVALID or ERROR. ERROR (VIES not reachable, no answer in
    time, country not available) is a normal result and is stored too: it means
    the number could not be confirmed, never that it is valid.
    """
    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id, Partner.organization_id == organization_id
        )
    )
    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )
    vat_number = partner.vat_number
    # End the read transaction: no database connection is held while waiting for VIES.
    db.commit()

    answer = adapter.check(vat_number)

    result = CheckResult(
        partner_id=partner_id,
        source=vies.SOURCE,
        status=answer.status.value,
        raw_response=answer.raw,
    )
    db.add(result)
    db.commit()
    return CheckRead.from_result(result)
