import uuid

# There is no sign-in yet, so every request belongs to this test organization.
# It is created by the migration "create partners table".
# Later the organization will come from the user's token instead.
TEST_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_organization_id() -> uuid.UUID:
    """FastAPI dependency: the organization of the current request."""
    return TEST_ORGANIZATION_ID
