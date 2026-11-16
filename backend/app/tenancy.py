import uuid
from fastapi import status

from app.errors import api_error
from app.auth import AuthenticatedUser

TEST_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_organization_id(user: AuthenticatedUser) -> uuid.UUID:
    """FastAPI dependency: the organization of the current request."""
    if user.organization_id is None:
        raise api_error(
            status.HTTP_403_FORBIDDEN,
            "no_organization",
            "No organisation is assigned to your account. Contact your administrator.",
        )
    return user.organization_id
