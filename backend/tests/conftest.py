import os
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.adapters.vies import CheckStatus, ViesResult, get_vies_adapter
from app.auth import TokenVerifier, get_token_verifier
from app.db.models import CheckResult, Partner, SecurityEvent
from app.db.session import engine, get_db

# No background copying of Keycloak events while testing (app/security/background.py).
os.environ["SECURITY_EVENTS_SYNC_SECONDS"] = "0"

from app.main import app
from app.security.keycloak import get_keycloak_client

VALID_ANSWER = {
    "isValid": True,
    "requestDate": "2026-10-31T13:46:27.800Z",
    "userError": "VALID",
    "name": "Muster Bau GmbH",
    "address": "Hauptstrasse 1\nAT-1010 Wien",
    "vatNumber": "U12345678",
}


class FakeVies:
    """Stands in for VIES in API tests: no internet, answer chosen by the test."""

    def __init__(self) -> None:
        self.result = ViesResult(CheckStatus.VALID, VALID_ANSWER)
        self.checked: list[str] = []

    def check(self, vat_number: str) -> ViesResult:
        self.checked.append(vat_number)
        return self.result


TEST_ISSUER = "http://keycloak.test/realms/bizpartnercheck"
TEST_AUDIENCE = "bizpartnercheck-api"
TEST_KEY_ID = "test-key"


class TokenFactory:
    """Signs access tokens like Keycloak does, with a key that exists only in the tests.

    The API checks them with the real TokenVerifier, so tests go through the same
    code as production; only the public key comes from here instead of Keycloak.
    """

    def __init__(self) -> None:
        self.private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )

    def make(
        self,
        *,
        sub: str = "user-1",
        email: str | None = "anna@example.com",
        name: str | None = "Anna Muster",
        expires_in: int = 300,
        issuer: str = TEST_ISSUER,
        audience: str | list[str] = TEST_AUDIENCE,
        typ: str = "Bearer",
        key: Any = None,
        kid: str = TEST_KEY_ID,
        algorithm: str = "RS256",
        omit: tuple[str, ...] = (),
        extra: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": issuer,
            "aud": audience,
            "sub": sub,
            "typ": typ,
            "iat": now,
            "exp": now + expires_in,
            "email": email,
            "name": name,
        }
        claims.update(extra or {})
        for claim in omit:
            claims.pop(claim, None)
        return jwt.encode(
            claims, key or self.private_key, algorithm=algorithm, headers={"kid": kid}
        )

    def verifier(self) -> TokenVerifier:
        public_key = self.private_key.public_key()

        def resolve(token: str) -> Any:
            if jwt.get_unverified_header(token).get("kid") != TEST_KEY_ID:
                raise jwt.PyJWKClientError("Unable to find a signing key")
            return public_key

        return TokenVerifier(TEST_ISSUER, TEST_AUDIENCE, resolve)


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture(scope="session")
def database_ready() -> None:
    """Stop with a clear hint instead of long errors when the database is not ready."""
    try:
        tables = inspect(engine).get_table_names()
    except OperationalError:
        pytest.exit(
            "The database is not reachable. Start it with "
            "`docker compose -f infra/docker-compose.yml up -d`.",
            returncode=1,
        )
    if not {"partners", "check_results", "security_events"} <= set(tables):
        pytest.exit(
            "The database tables are missing. Run `uv run alembic upgrade head` in `backend`.",
            returncode=1,
        )


@pytest.fixture
def db(database_ready: None) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    Tests use the real database (tables from `alembic upgrade head`),
    but leave no data behind. Each test starts without partners, checks and
    security log entries;
    your own data comes back when the transaction is rolled back.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session.execute(delete(CheckResult))
    session.execute(delete(Partner))
    # The security log is append-only; this transaction may empty it (it is rolled back).
    session.execute(
        text("SET LOCAL bizpartnercheck.allow_security_event_delete = 'on'")
    )
    session.execute(delete(SecurityEvent))
    session.execute(
        text("SET LOCAL bizpartnercheck.allow_security_event_delete = 'off'")
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def fake_vies() -> FakeVies:
    return FakeVies()


@pytest.fixture
def anonymous_client(
    db: Session, fake_vies: FakeVies, tokens: TokenFactory
) -> Iterator[TestClient]:
    """A client without sign-in token."""
    app.dependency_overrides[get_db] = lambda: db
    # Tests never call the real VIES or the real Keycloak.
    app.dependency_overrides[get_vies_adapter] = lambda: fake_vies
    app.dependency_overrides[get_token_verifier] = tokens.verifier
    app.dependency_overrides[get_keycloak_client] = lambda: None
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(anonymous_client: TestClient, tokens: TokenFactory) -> TestClient:
    """A client of a signed-in user (valid token on every request)."""
    anonymous_client.headers["Authorization"] = f"Bearer {tokens.make()}"
    return anonymous_client


@pytest.fixture
def admin_token(tokens: TokenFactory) -> str:
    """Token of an organisation admin (realm role "org-admin")."""
    return tokens.make(
        sub="admin-1",
        email="admin@example.com",
        name="Anna Admin",
        extra={
            "realm_access": {"roles": ["org-admin", "default-roles-bizpartnercheck"]}
        },
    )
