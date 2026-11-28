import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters import bmf, firmenbuch, gisa, hfu, vies
from app.adapters.base import CheckStatus, CheckSubject, SourceAdapter
from app.adapters.bmf import get_bmf_adapter
from app.adapters.firmenbuch import get_firmenbuch_adapter
from app.adapters.gisa import get_gisa_adapter
from app.adapters.hfu import get_hfu_adapter
from app.adapters.vies import get_vies_adapter
from app.db.session import get_db
from app.errors import api_error
from app.partners.register import (
    InvalidRegisterNumber,
    normalize_register_number,
    validate_register_number,
)
from app.partners.vat import (
    InvalidVatNumber,
    normalize_vat_number,
    validate_vat_number,
)
from app.tenancy import get_current_organization_id
from app.db.models import CheckResult, CheckRun, Organization, Partner
from app.checks.overall import Level, overall_result, sources_left_out
from app.checks.runs import RUNNING

router = APIRouter(prefix="/partners", tags=["partners"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
Vies = Annotated[SourceAdapter, Depends(get_vies_adapter)]
Bmf = Annotated[SourceAdapter, Depends(get_bmf_adapter)]
Hfu = Annotated[SourceAdapter, Depends(get_hfu_adapter)]
Firmenbuch = Annotated[SourceAdapter, Depends(get_firmenbuch_adapter)]
Gisa = Annotated[SourceAdapter, Depends(get_gisa_adapter)]
# Sources whose latest result the partner list shows.
LISTED_SOURCES = (vies.SOURCE, bmf.SOURCE, hfu.SOURCE, firmenbuch.SOURCE, gisa.SOURCE)

UNIQUE_VAT_CONSTRAINT = "uq_partners_organization_vat"
UNIQUE_REGISTER_CONSTRAINT = "uq_partners_organization_register"

SORT_FIELDS = ("created_at", "company_name", "vat_number", "company_register_number")


class PartnerCreate(BaseModel):
    """A partner needs a VAT number, a company register number, or both."""

    vat_number: str | None = None
    # Austrian company register number (Firmenbuchnummer), e.g. "FN 123456a".
    company_register_number: str | None = None
    company_name: str | None = Field(default=None, max_length=255)


class PartnerUpdate(BaseModel):
    """Fields that can be edited for an existing partner.

    The company name can always be changed. A VAT number or company register number
    can only be added while the partner has none: a number that is already set
    identifies the partner in its stored checks and is never changed or removed.
    """

    company_name: str | None = Field(default=None, max_length=255)
    vat_number: str | None = None
    company_register_number: str | None = None


class RegisterFlag(BaseModel):
    """A Firmenbuch entry that marks the company as not (fully) active."""

    # deleted, insolvency or liquidation
    kind: str
    # In words, e.g. "insolvency proceedings".
    label: str
    # The register's own text, e.g. "Konkurs eröffnet".
    text: str | None = None
    date: str | None = None
    # Insolvency proceedings that are over (gives REVIEW, not FINDING).
    ended: bool = False


class RegisterPerson(BaseModel):
    """A managing director, shareholder, ...: only name, role and start date."""

    name: str | None
    role: str | None
    since: str | None = None


class RegisterDetails(BaseModel):
    """What the Firmenbuch says about the company (S4.5)."""

    # False: the register has no company with this number.
    found: bool
    register_number: str | None = None
    legal_form: str | None = None
    seat: str | None = None
    flags: list[RegisterFlag] = []
    persons: list[RegisterPerson] = []

    @classmethod
    def from_raw(cls, raw: dict) -> "RegisterDetails | None":
        if raw.get("notFound") is True:
            return cls(found=False, register_number=firmenbuch.register_number(raw))
        if not firmenbuch.company_name(raw):
            return None  # an error: nothing to show
        persons = raw.get("persons")
        return cls(
            found=True,
            register_number=firmenbuch.register_number(raw),
            legal_form=firmenbuch.legal_form(raw),
            seat=firmenbuch.seat(raw),
            flags=[
                RegisterFlag(
                    kind=flag["kind"],
                    label=firmenbuch.FLAG_LABELS.get(flag["kind"], flag["kind"]),
                    text=flag.get("text"),
                    date=flag.get("date"),
                    ended=flag.get("ended", False),
                )
                for flag in firmenbuch.status_flags(raw)
            ],
            persons=[
                RegisterPerson(
                    name=person.get("name"),
                    role=person.get("role"),
                    since=person.get("since"),
                )
                for person in persons
                if isinstance(person, dict)
            ]
            if isinstance(persons, list)
            else [],
        )


class LicenceRead(BaseModel):
    """One business licence from GISA (S4.6)."""

    gisa_number: str | None
    # The trade (Gewerbewortlaut), e.g. "Baumeister", and its key (Gewerbeschlüssel).
    trade: str | None
    trade_key: str | None = None
    # active, suspended, ended or unknown
    state: str
    start: str | None = None
    end: str | None = None
    # Since when the licence is suspended (ruhend), if it is.
    suspended_since: str | None = None
    # The authority that issued it, e.g. "Magistrat der Stadt Krems".
    authority: str | None = None
    location: str | None = None
    # The gewerberechtlicher Geschäftsführer: name and start date only.
    manager_name: str | None = None
    manager_since: str | None = None

    @classmethod
    def from_raw(cls, raw: dict) -> list["LicenceRead"] | None:
        if not isinstance(raw.get("licences"), list):
            return None  # an error: nothing to show
        result = []
        for licence in gisa.licences(raw):
            manager = gisa.manager_of(licence, gisa.check_day(raw)) or {}
            result.append(
                cls(
                    gisa_number=licence.get("gisaNumber"),
                    trade=licence.get("trade"),
                    trade_key=licence.get("tradeKey"),
                    state=licence["state"],
                    start=licence.get("start"),
                    end=licence.get("end"),
                    suspended_since=(
                        licence.get("suspendedFrom")
                        if licence["state"] == gisa.SUSPENDED
                        else None
                    ),
                    authority=licence.get("authority"),
                    location=licence.get("location"),
                    manager_name=manager.get("name"),
                    manager_since=manager.get("since"),
                )
            )
        return result


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
    # Firmenbuch only: legal form, seat, status flags and persons.
    register_details: RegisterDetails | None = None
    # GISA only: every licence with trade, number, status, dates and manager.
    licences: list[LicenceRead] | None = None

    @classmethod
    def from_result(cls, result: CheckResult) -> "CheckRead":
        status_ = CheckStatus(result.status)
        is_vies = result.source == vies.SOURCE
        is_register = result.source == firmenbuch.SOURCE
        raw = result.raw_response
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
                vies.company_name(raw)
                if is_vies and status_ == CheckStatus.OK
                else firmenbuch.company_name(raw)
                if is_register
                else None
            ),
            address=(
                vies.registered_address(raw)
                if is_vies and status_ == CheckStatus.OK
                else firmenbuch.address_text(raw)
                if is_register
                else None
            ),
            consultation_number=(vies.consultation_number(raw) if is_vies else None),
            register_details=(RegisterDetails.from_raw(raw) if is_register else None),
            licences=(
                LicenceRead.from_raw(raw) if result.source == gisa.SOURCE else None
            ),
        )


class LatestOverallRead(BaseModel):
    """Overall result of the partner's latest finished check run (S5.2)."""

    run_id: uuid.UUID
    level: Level
    summary: str
    finished_at: datetime | None


class PartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vat_number: str | None
    company_register_number: str | None
    company_name: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    latest_vies_check: CheckRead | None = None
    latest_bmf_check: CheckRead | None = None
    latest_hfu_check: CheckRead | None = None
    latest_firmenbuch_check: CheckRead | None = None
    latest_gisa_check: CheckRead | None = None
    # GREEN, YELLOW or RED of the latest finished run; null if never checked in a run.
    latest_overall: LatestOverallRead | None = None


class PartnerPage(BaseModel):
    items: list[PartnerRead]
    total: int
    page: int
    page_size: int
    total_pages: int


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


def _contains(value: str) -> str:
    """LIKE pattern for "contains value": % and _ typed by the user are literal."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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
        company_name=body.company_name.strip()
        if body.company_name and body.company_name.strip()
        else None,
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


@router.get("", response_model=PartnerPage)
def list_partners(
    db: DbSession,
    organization_id: OrganizationId,
    search: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> PartnerPage:

    allowed_sort_fields = {
        "company_name": Partner.company_name,
        "vat_number": Partner.vat_number,
        "company_register_number": Partner.company_register_number,
        "created_at": Partner.created_at,
    }

    if sort_by not in allowed_sort_fields:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_sort",
            f"Partners can be sorted by: {', '.join(SORT_FIELDS)}.",
            field="sort_by",
        )

    query = select(Partner).where(
        Partner.organization_id == organization_id,
        Partner.is_archived.is_(False),
    )

    if search and search.strip():
        term = search.strip()
        # Numbers are stored normalised ("ATU12345678", "123456a"), so the search
        # term is normalised the same way: "atu 1234" and "FN 123456a" are found too.
        conditions = [Partner.company_name.ilike(_contains(term), escape="\\")]
        vat_term = normalize_vat_number(term)
        if vat_term:
            conditions.append(
                Partner.vat_number.ilike(_contains(vat_term), escape="\\")
            )
        register_term = normalize_register_number(term)
        if register_term:
            conditions.append(
                Partner.company_register_number.ilike(
                    _contains(register_term), escape="\\"
                )
            )
        query = query.where(or_(*conditions))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    sort_column = allowed_sort_fields[sort_by]
    # Partners without a name or number come last in both directions.
    ordering = (
        asc(sort_column).nulls_last()
        if sort_order == "asc"
        else desc(sort_column).nulls_last()
    )

    partners = db.scalars(
        query.order_by(ordering, Partner.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = _with_latest_checks(db, partners)

    return PartnerPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


def _with_latest_checks(db: Session, partners: Sequence[Partner]) -> list[PartnerRead]:
    """The partners with their latest result per listed source (one query for all of them)."""
    partner_ids = [partner.id for partner in partners]
    latest = db.scalars(
        select(CheckResult)
        .where(
            CheckResult.partner_id.in_(partner_ids),
            CheckResult.source.in_(LISTED_SOURCES),
        )
        # Latest result per partner and source (PostgreSQL DISTINCT ON).
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

    overall_by = _latest_overall(db, partners)

    return [
        PartnerRead(
            id=partner.id,
            vat_number=partner.vat_number,
            company_register_number=partner.company_register_number,
            company_name=partner.company_name,
            is_archived=partner.is_archived,
            created_at=partner.created_at,
            updated_at=partner.updated_at,
            latest_vies_check=read(partner, vies.SOURCE),
            latest_bmf_check=read(partner, bmf.SOURCE),
            latest_hfu_check=read(partner, hfu.SOURCE),
            latest_firmenbuch_check=read(partner, firmenbuch.SOURCE),
            latest_gisa_check=read(partner, gisa.SOURCE),
            latest_overall=overall_by.get(partner.id),
        )
        for partner in partners
    ]


def _latest_overall(
    db: Session, partners: Sequence[Partner]
) -> dict[uuid.UUID, LatestOverallRead]:
    """Overall result of each partner's latest finished run (two queries for all)."""
    by_id = {partner.id: partner for partner in partners}
    runs = db.scalars(
        select(CheckRun)
        .where(CheckRun.partner_id.in_(by_id), CheckRun.status != RUNNING)
        .order_by(CheckRun.partner_id, CheckRun.started_at.desc(), CheckRun.id.desc())
        .ext(distinct_on(CheckRun.partner_id))
    ).all()
    if not runs:
        return {}
    statuses: dict[uuid.UUID, dict[str, str]] = {run.id: {} for run in runs}
    for run_id, source, status_ in db.execute(
        select(CheckResult.run_id, CheckResult.source, CheckResult.status).where(
            CheckResult.run_id.in_(statuses)
        )
    ):
        statuses[run_id][source] = status_
    overall: dict[uuid.UUID, LatestOverallRead] = {}
    for run in runs:
        partner = by_id[run.partner_id]
        result = overall_result(
            run.sources,
            statuses[run.id],
            not_checked=sources_left_out(
                run.sources, bool(partner.company_register_number)
            ),
        )
        overall[run.partner_id] = LatestOverallRead(
            run_id=run.id,
            level=result.level,
            summary=result.summary,
            finished_at=run.finished_at,
        )
    return overall


# Returns archived partners belonging to the current organization.
@router.get("/archived", response_model=list[PartnerRead])
def list_archived_partners(
    db: DbSession,
    organization_id: OrganizationId,
) -> list[PartnerRead]:
    partners = db.scalars(
        select(Partner)
        .where(
            Partner.organization_id == organization_id,
            Partner.is_archived.is_(True),
        )
        .order_by(Partner.created_at.desc(), Partner.id)
    ).all()
    return _with_latest_checks(db, partners)


@router.get("/{partner_id}", response_model=PartnerRead)
def get_partner(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
) -> PartnerRead:
    """Return one partner belonging to the current organization."""
    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id,
            Partner.organization_id == organization_id,
        )
    )
    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )
    return _with_latest_checks(db, [partner])[0]


@router.get("/{partner_id}/checks", response_model=list[CheckRead])
def get_partner_checks(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
) -> list[CheckRead]:
    """Return all stored checks for one partner, newest first."""

    partner = db.scalar(
        select(Partner.id).where(
            Partner.id == partner_id,
            Partner.organization_id == organization_id,
        )
    )

    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )

    checks = db.scalars(
        select(CheckResult)
        .where(CheckResult.partner_id == partner_id)
        .order_by(
            CheckResult.checked_at.desc(),
            CheckResult.id.desc(),
        )
    ).all()

    return [CheckRead.from_result(check) for check in checks]


# Updates a partner's company name while ensuring it belongs to the current organization.
# Existing identifiers and verification history remain unchanged.
@router.patch("/{partner_id}", response_model=PartnerRead)
def update_partner(
    partner_id: uuid.UUID,
    body: PartnerUpdate,
    db: DbSession,
    organization_id: OrganizationId,
) -> Partner:
    """Update the company name and add a missing VAT or company register number.

    A number that is already set is never changed or removed (409 identifier_locked):
    the stored checks were made with it (docs/partner-directory.md).
    """

    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id,
            Partner.organization_id == organization_id,
        )
    )

    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )

    vat_number = _added_identifier(
        body, "vat_number", partner.vat_number, validate_vat_number
    )
    register_number = _added_identifier(
        body,
        "company_register_number",
        partner.company_register_number,
        validate_register_number,
    )
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

    if "company_name" in body.model_fields_set:
        partner.company_name = (
            body.company_name.strip()
            if body.company_name and body.company_name.strip()
            else None
        )
    if vat_number is not None:
        partner.vat_number = vat_number
    if register_number is not None:
        partner.company_register_number = register_number

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Two requests at the same time: the unique constraint catches the second one.
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == UNIQUE_VAT_CONSTRAINT and vat_number is not None:
            raise _duplicate_vat(vat_number) from exc
        if constraint == UNIQUE_REGISTER_CONSTRAINT and register_number is not None:
            raise _duplicate_register(register_number) from exc
        raise
    db.refresh(partner)

    return partner


def _added_identifier(
    body: PartnerUpdate,
    field: str,
    current: str | None,
    validate: Callable[[str], str],
) -> str | None:
    """The normalised number to add, None if nothing changes, or a 409/422.

    Sending the number the partner already has (in any spelling) or an empty value
    for a missing number changes nothing. A different number, or an empty value for
    a number that is set, is refused: stored checks were made with that number.
    """
    if field not in body.model_fields_set:
        return None
    value = getattr(body, field)
    if _blank(value):
        if current is not None:
            raise _identifier_locked(field)
        return None
    try:
        number = validate(value or "")
    except (InvalidVatNumber, InvalidRegisterNumber) as exc:
        code = (
            "invalid_vat_format"
            if field == "vat_number"
            else "invalid_register_number_format"
        )
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT, code, str(exc), field=field
        ) from exc
    if current is None:
        return number
    if number == current:
        return None
    raise _identifier_locked(field)


def _identifier_locked(field: str) -> HTTPException:
    name = "VAT number" if field == "vat_number" else "company register number"
    return api_error(
        status.HTTP_409_CONFLICT,
        "identifier_locked",
        f"The {name} of a partner cannot be changed or removed, because its checks "
        "were made with it. To use another number, archive this partner and add it "
        "again.",
        field=field,
    )


# Archives a partner without deleting its verification history.
@router.patch("/{partner_id}/archive", response_model=PartnerRead)
def archive_partner(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
) -> Partner:
    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id,
            Partner.organization_id == organization_id,
        )
    )

    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )

    partner.is_archived = True
    db.commit()
    db.refresh(partner)

    return partner


# Restores an archived partner to the active directory.
@router.patch("/{partner_id}/restore", response_model=PartnerRead)
def restore_partner(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
) -> Partner:
    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id,
            Partner.organization_id == organization_id,
        )
    )

    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )

    partner.is_archived = False
    db.commit()
    db.refresh(partner)

    return partner


@router.post(
    "/{partner_id}/checks/vies",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner has no VAT number or is archived"},
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
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner is archived"},
    },
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


@router.post(
    "/{partner_id}/checks/hfu",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner has no VAT number"},
    },
)
def run_hfu_check(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
    adapter: Hfu,
) -> CheckRead:
    """Ask the ÖGK whether the partner is on the HFU list today and store the answer.

    OK: on the list (no withholding for contractor liability). FINDING: not on the
    list (a withholding may apply to payments). ERROR: the service could not be
    asked, or the organisation's own VAT number (the requester) is not set.
    The ÖGK identifies the partner by its VAT number.
    """
    return _run_check(db, organization_id, partner_id, adapter)


@router.post(
    "/{partner_id}/checks/firmenbuch",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner has no company register number or is archived"},
    },
)
def run_firmenbuch_check(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
    adapter: Firmenbuch,
) -> CheckRead:
    """Ask the Firmenbuch (Austrian company register) about the partner's FN.

    OK: registered and active, with name, seat and legal form. FINDING: deleted,
    insolvency or liquidation (the flag is shown), or no company with this FN.
    REVIEW: only insolvency proceedings that have ended. ERROR: the register could
    not be asked (also when the API key is not set on the server).
    """
    return _run_check(
        db,
        organization_id,
        partner_id,
        adapter,
        needs_vat_number=False,
        needs_register_number=True,
    )


@router.post(
    "/{partner_id}/checks/gisa",
    response_model=CheckRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner has no company register number or is archived"},
    },
)
def run_gisa_check(
    partner_id: uuid.UUID,
    db: DbSession,
    organization_id: OrganizationId,
    adapter: Gisa,
) -> CheckRead:
    """Ask GISA for the partner's business licences (searched by FN).

    OK: at least one active licence (all licences are listed). FINDING: licences,
    but none active. REVIEW: no licence found (many companies need none), or the
    status of the licences is unclear.
    ERROR: GISA could not be asked (also when the API key is not set on the server).
    """
    return _run_check(
        db,
        organization_id,
        partner_id,
        adapter,
        needs_vat_number=False,
        needs_register_number=True,
    )


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
    needs_register_number: bool = False,
) -> CheckRead:
    """Check one partner against one source and store the common result.

    Sources that need a VAT number (VIES) refuse partners without one with 409;
    the BMF list can also match the company register number or the name.
    """
    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id,
            Partner.organization_id == organization_id,
        )
    )

    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )
    if partner.is_archived:
        # The partner exists (it is ours), so 409 and not 404: restore it first.
        raise api_error(
            status.HTTP_409_CONFLICT,
            "partner_archived",
            "This partner is archived. Restore it before checking it again.",
        )
    if partner.vat_number is None and needs_vat_number:
        # Added by company register number only: VIES needs a VAT number.
        raise api_error(
            status.HTTP_409_CONFLICT,
            "no_vat_number",
            f"This partner has no VAT number, so {adapter.source} cannot check it.",
            field="vat_number",
        )
    if partner.company_register_number is None and needs_register_number:
        # E.g. a foreign partner: the Firmenbuch and GISA are searched by FN.
        name = "the Firmenbuch" if adapter.source == firmenbuch.SOURCE else "GISA"
        raise api_error(
            status.HTTP_409_CONFLICT,
            "no_register_number",
            f"This partner has no company register number, so {name} cannot check it.",
            field="company_register_number",
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
