import time
import logging
import re

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from collections import defaultdict
from threading import Lock
from app.db.models import Organization
from app.db.session import get_db
from app.errors import api_error
from app.partners.vat import InvalidVatNumber, validate_vat_number
from app.security.keycloak_registration import (
    KeycloakRegistrationClient,
    KeycloakRegistrationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/registration", tags=["registration"])
# Allow 5 registration attempts per IP address every 15 minutes.
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 15 * 60

_registration_attempts: dict[str, list[float]] = defaultdict(list)
_rate_limit_lock = Lock()


def check_rate_limit(ip_address: str) -> bool:
    now = time.monotonic()

    with _rate_limit_lock:
        attempts = _registration_attempts[ip_address]
        attempts[:] = [
            timestamp
            for timestamp in attempts
            if now - timestamp < RATE_WINDOW_SECONDS
        ]

        if len(attempts) >= RATE_LIMIT:
            return False

        attempts.append(now)
        return True


class RegistrationRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    admin_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    vat_number: str | None = Field(default=None, max_length=20)
    website: str = Field(default="", max_length=255)


@router.post("", status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    body: RegistrationRequest,
    db: Session = Depends(get_db),
):
    ip_address = request.client.host if request.client else "unknown"

    if not check_rate_limit(ip_address):
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "registration_rate_limit",
            "Too many registration attempts. Please try again later.",
        )
    if body.website.strip():
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            "registration_rejected",
            "Registration could not be completed.",
        )
    company_name = body.company_name.strip()
    admin_name = body.admin_name.strip()
    email = body.email.strip().lower()

    if not company_name or not admin_name:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_registration",
            "Company name and administrator name are required.",
        )

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_email",
            "Please enter a valid email address.",
            field="email",
        )

    vat_number = None

    if body.vat_number and body.vat_number.strip():
        try:
            vat_number = validate_vat_number(body.vat_number)
        except InvalidVatNumber as exc:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_vat_format",
                str(exc),
                field="vat_number",
            ) from exc

    organization = Organization(
        name=company_name,
        vat_number=vat_number,
    )

    db.add(organization)

    keycloak = KeycloakRegistrationClient()
    keycloak_user_id = None

    try:
        # Obtain the organization ID without committing yet.
        db.flush()

        # Create the first administrator in Keycloak.
        keycloak_user_id = keycloak.create_user(
            email=email,
            admin_name=admin_name,
            organization_id=organization.id,
        )

        keycloak.assign_org_admin_role(keycloak_user_id)
        keycloak.send_verification_email(keycloak_user_id)

        # Commit only after Keycloak operations succeed.
        db.commit()

        return {
            "message": (
                "Registration received. Your account will be activated "
                "after email verification."
            )
        }

    except KeycloakRegistrationError as exc:
        db.rollback()

        if keycloak_user_id:
            try:
                keycloak.delete_user(keycloak_user_id)
            except KeycloakRegistrationError:
                logger.exception(
                    "Could not remove Keycloak user during registration rollback."
                )

        if "already registered" in str(exc).lower():
            raise api_error(
                status.HTTP_409_CONFLICT,
                "email_already_registered",
                "This email address is already registered.",
                field="email",
            ) from exc

        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "registration_unavailable",
            "Registration is temporarily unavailable. Please try again.",
        ) from exc

    except IntegrityError as exc:
        db.rollback()

        if keycloak_user_id:
            try:
                keycloak.delete_user(keycloak_user_id)
            except KeycloakRegistrationError:
                logger.exception(
                    "Could not remove Keycloak user during database rollback."
                )

        constraint = getattr(
            getattr(exc.orig, "diag", None),
            "constraint_name",
            None,
        )

        if constraint == "uq_organizations_vat":
            raise api_error(
                status.HTTP_409_CONFLICT,
                "duplicate_organization_vat",
                "An organization with this VAT number already exists.",
                field="vat_number",
            ) from exc

        raise