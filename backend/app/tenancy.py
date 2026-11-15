import uuid
from fastapi import HTTPException
from app.auth import AuthenticatedUser

TEST_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_organization_id(user: AuthenticatedUser) -> uuid.UUID:
    """FastAPI dependency: the organization of the current request."""
    if user.organization_id is None:
        raise HTTPException(status_code=403, detail="No organization assigned.")
    return user.organization_id
