"""The signed-in user's own organisation: name and its own VAT number (SCRUM-40).

GET /api/v1/organization   name and VAT number, for every signed-in user
PUT /api/v1/organization   change the VAT number, organisation admins only

The organisation's VAT number is sent to VIES as the requester with every VAT
check. VIES then answers with a consultation number: proof that the check was
made. A wrong number makes VIES refuse every check (INVALID_REQUESTER_INFO), so
the format is checked before it is saved. Details: docs/vies.md
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import OrgAdmin
from app.db.models import Organization
from app.db.session import get_db
from app.errors import api_error
from app.partners.vat import InvalidVatNumber, validate_vat_number
from app.tenancy import get_current_organization_id

router = APIRouter(prefix="/organization", tags=["organization"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    # Stored normalised (e.g. "ATU12345678"); null until an admin sets it.
    vat_number: str | None


class OrganizationUpdate(BaseModel):
    # Empty or null removes the number: VIES is then asked without a requester and
    # gives no consultation number.
    vat_number: str | None = None


def _organization(db: Session, organization_id: uuid.UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "organization_not_found",
            "Your organisation does not exist.",
        )
    return organization


def _read(organization: Organization) -> OrganizationRead:
    return OrganizationRead(
        id=organization.id,
        name=organization.name,
        vat_number=organization.vat_number,
    )


@router.get("", response_model=OrganizationRead)
def get_organization(
    db: DbSession, organization_id: OrganizationId
) -> OrganizationRead:
    """The organisation of the signed-in user."""
    return _read(_organization(db, organization_id))


@router.put(
    "",
    response_model=OrganizationRead,
    responses={
        403: {"description": "Not an organisation admin"},
        422: {"description": "The VAT number does not have a valid format"},
    },
)
def update_organization(
    body: OrganizationUpdate,
    _admin: OrgAdmin,
    db: DbSession,
    organization_id: OrganizationId,
) -> OrganizationRead:
    """Set or remove the organisation's own VAT number (the VIES requester)."""
    vat_number = None
    if body.vat_number is not None and body.vat_number.strip():
        try:
            vat_number = validate_vat_number(body.vat_number)
        except InvalidVatNumber as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_vat_format",
                str(exc),
                field="vat_number",
            ) from exc

    organization = _organization(db, organization_id)
    organization.vat_number = vat_number
    db.commit()
    db.refresh(organization)
    return _read(organization)
