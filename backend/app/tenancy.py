import uuid

# Users sign in (app/auth.py), but tokens do not carry an organization yet, so every
# signed-in user belongs to this test organization. It is created by the migration
# "create partners table". With story S2.3 the organization will come from the token.
TEST_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def get_current_organization_id() -> uuid.UUID:
    """FastAPI dependency: the organization of the current request."""
    return TEST_ORGANIZATION_ID
