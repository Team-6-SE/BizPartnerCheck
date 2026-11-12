import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import bmf, vies
from app.adapters.base import CheckStatus, CheckSubject, SourceAdapter
from app.adapters.bmf import get_bmf_adapter
from app.adapters.vies import get_vies_adapter
from app.db.models import CheckResult, Partner
from app.db.session import get_db
from app.errors import api_error
from app.partners.register import InvalidRegisterNumber, validate_register_number
from app.partners.vat import InvalidVatNumber, validate_vat_number
from app.tenancy import get_current_organization_id
from app.db.models import CheckResult, Organization, Partner

router = APIRouter(prefix="/partners", tags=["partners"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
Vies = Annotated[SourceAdapter, Depends(get_vies_adapter)]
Bmf = Annotated[SourceAdapter, Depends(get_bmf_adapter)]

UNIQUE_VAT_CONSTRAINT = "uq_partners_organization_vat"
UNIQUE_REGISTER_CONSTRAINT = "uq_partners_organization_register"


class PartnerCreate(BaseModel):
    """A partner needs a VAT number, a company register number, or both."""

    vat_number: str | None = None
    # Austrian company register number (Firmenbuchnummer), e.g. "FN 123456a".
    company_register_number: str | None = None

class CheckRead(BaseModel):
    id: uuid.UUID
    source: str
    status: CheckStatus
    checked_at: datetime
    # Explanation for people, e.g. why the check gave ERROR.
    message: str
    # Registered name from VIES, if the country shares it.
    company_name: str | None
    # How current the source's data was (imported lists); null for live sources.
    data_as_of: datetime | None = None
    address: str | None = None
    consultation_number: str | None = None

    @classmethod
    def from_result(cls, result: CheckResult) -> "CheckRead":
        status_ = CheckStatus(result.status)
        is_vies = result.source == vies.SOURCE
        message = result.explanation
        if message is None and is_vies:
            # Checks stored before the explanation was saved.
            message = vies.describe(status_, result.raw_response)
        return cls(
            id=result.id,
            source=result.source,
            status=status_,
            checked_at=result.checked_at,
            message=message or "",
            data_as_of=result.data_as_of,
            company_name=(
                vies.company_name(result.raw_response)
                if is_vies and status_ == CheckStatus.OK
                else None
            ),
            address=(
                vies.registered_address(result.raw_response)
                if is_vies and status_ == CheckStatus.OK
                else None
            ),
            consultation_number=(
                vies.consultation_number(result.raw_response) if is_vies else None
            ),
        )


class PartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vat_number: str | None
    company_register_number: str | None
    created_at: datetime
    latest_vies_check: CheckRead | None = None
    latest_bmf_check: CheckRead | None = None


def _duplicate_vat(vat_number: str) -> HTTPException:
    return api_error(
        status.HTTP_409_CONFLICT,
        "duplicate_partner",
        f"A partner with VAT number {vat_number} already exists.",
        field="vat_number",
    )


def _duplicate_register(register_number: str) -> HTTPException:
    return api_error(
        status.HTTP_409_CONFLICT,
        "duplicate_partner",
        f"A partner with company register number FN {register_number} already exists.",
        field="company_register_number",
    )


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _validated_identifiers(body: PartnerCreate) -> tuple[str | None, str | None]:
    """Normalised VAT number and company register number, or a 422 naming the field."""
    if _blank(body.vat_number) and _blank(body.company_register_number):
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "missing_identifier",
            "Please enter a VAT number (e.g. ATU12345678) "
            "or a company register number (e.g. 123456a).",
            field="vat_number",
        )

    vat_number = None
    if not _blank(body.vat_number):
        try:
            vat_number = validate_vat_number(body.vat_number or "")
        except InvalidVatNumber as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_vat_format",
                str(exc),
                field="vat_number",
            ) from exc

    register_number = None
    if not _blank(body.company_register_number):
        try:
            register_number = validate_register_number(
                body.company_register_number or ""
            )
        except InvalidRegisterNumber as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_register_number_format",
                str(exc),
                field="company_register_number",
            ) from exc

    return vat_number, register_number


@router.post("", response_model=PartnerRead, status_code=status.HTTP_201_CREATED)
def create_partner(
    body: PartnerCreate, db: DbSession, organization_id: OrganizationId
) -> Partner:
    vat_number, register_number = _validated_identifiers(body)

    if vat_number is not None and db.scalar(
        select(Partner.id).where(
            Partner.organization_id == organization_id,
            Partner.vat_number == vat_number,
        )
    ):
        raise _duplicate_vat(vat_number)
    if register_number is not None and db.scalar(
        select(Partner.id).where(
            Partner.organization_id == organization_id,
            Partner.company_register_number == register_number,
        )
    ):
        raise _duplicate_register(register_number)

    partner = Partner(
        organization_id=organization_id,
        vat_number=vat_number,
        company_register_number=register_number,
    )
    db.add(partner)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Two requests at the same time: the unique constraint catches the second one.
        # Any other integrity problem is a real error and must not look like a duplicate.
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == UNIQUE_VAT_CONSTRAINT and vat_number is not None:
            raise _duplicate_vat(vat_number) from exc
        if constraint == UNIQUE_REGISTER_CONSTRAINT and register_number is not None:
            raise _duplicate_register(register_number) from exc
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

    # Latest result per partner and source (PostgreSQL DISTINCT ON), one query for all.
    latest = db.scalars(
        select(CheckResult)
        .join(Partner, CheckResult.partner_id == Partner.id)
        .where(
            Partner.organization_id == organization_id,
            CheckResult.source.in_((vies.SOURCE, bmf.SOURCE)),
        )
        .order_by(
            CheckResult.partner_id,
            CheckResult.source,
            CheckResult.checked_at.desc(),
            CheckResult.id.desc(),
        )
        .ext(distinct_on(CheckResult.partner_id, CheckResult.source))
    ).all()
    latest_by = {(result.partner_id, result.source): result for result in latest}

    def read(partner: Partner, source: str) -> CheckRead | None:
        result = latest_by.get((partner.id, source))
        return CheckRead.from_result(result) if result else None

    return [
        PartnerRead(
            id=partner.id,
            vat_number=partner.vat_number,
            company_register_number=partner.company_register_number,
            created_at=partner.created_at,
            latest_vies_check=read(partner, vies.SOURCE),
            latest_bmf_check=read(partner, bmf.SOURCE),
        )
        for partner in partners
    ]


@router.post(
    "/{partner_id}/checks/vies",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner has no VAT number"},
    },
)
def run_vies_check(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
    adapter: Vies,
) -> CheckRead:
    """Ask VIES now and store the answer.

    The result is OK (valid), FINDING (not valid) or ERROR. ERROR (VIES not
    reachable, no answer in time, country not available) is a normal result and is
    stored too: it means the number could not be confirmed, never that it is valid.
    """
    return _run_check(db, organization_id, partner_id, adapter)


@router.post(
    "/{partner_id}/checks/bmf",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"description": "Partner not found"}},
)
def run_bmf_check(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
    adapter: Bmf,
) -> CheckRead:
    """Compare the partner with the BMF list of fake companies and store the result.

    FINDING: same VAT or Firmenbuch number on the list. REVIEW: only the same company
    name (from the latest valid VIES check) - a person must look. OK: not on the list.
    ERROR: the list was never imported. The result always carries `data_as_of` (time
    of the last import) and a warning if the list is older than 24 hours.
    Partners without a VAT number are matched by company register number and name.
    """
    return _run_check(db, organization_id, partner_id, adapter, needs_vat_number=False)


def _company_name(db: Session, partner_id: uuid.UUID) -> str | None:
    """The registered name from the latest valid VIES check, if there is one."""
    result = db.scalar(
        select(CheckResult)
        .where(
            CheckResult.partner_id == partner_id,
            CheckResult.source == vies.SOURCE,
            CheckResult.status == CheckStatus.OK.value,
        )
        .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
        .limit(1)
    )
    # Fake VIES names must never be used for a real comparison.
    if result is None or result.raw_response.get("fake"):
        return None
    return vies.company_name(result.raw_response)


def _run_check(
    db: Session,
    organization_id: uuid.UUID,
    partner_id: uuid.UUID,
    adapter: SourceAdapter,
    *,
    needs_vat_number: bool = True,
) -> CheckRead:
    """Check one partner against one source and store the common result.

    Sources that need a VAT number (VIES) refuse partners without one with 409;
    the BMF list can also match the company register number or the name.
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
    if partner.vat_number is None and needs_vat_number:
        # Added by company register number only: VIES needs a VAT number.
        raise api_error(
            status.HTTP_409_CONFLICT,
            "no_vat_number",
            f"This partner has no VAT number, so {adapter.source} cannot check it.",
            field="vat_number",
        )
    requester_vat = db.scalar(
        select(Organization.vat_number).where(Organization.id == organization_id)
    )
    subject = CheckSubject(
        vat_number=partner.vat_number,
        register_number=partner.company_register_number,
        name=_company_name(db, partner_id),
        requester_vat=requester_vat,
    )
    # End the read transaction: no database connection is held while waiting for the source.
    db.commit()

    answer = adapter.check(subject)

    result = CheckResult(
        partner_id=partner_id,
        source=answer.source,
        status=answer.status.value,
        checked_at=answer.retrieved_at,
        raw_response=answer.raw,
        explanation=answer.explanation,
        data_as_of=answer.data_as_of,
    )
    db.add(result)
    db.commit()
    return CheckRead.from_result(result)
