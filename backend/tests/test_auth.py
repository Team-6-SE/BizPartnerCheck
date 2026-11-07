"""Sign-in token checks: every /api/v1 request needs a valid Keycloak access token."""

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import (
    AuthUnavailable,
    TokenVerifier,
    get_token_verifier,
    jwks_key_resolver,
)
from app.main import app

PROTECTED = [
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/partners"),
    ("POST", "/api/v1/partners"),
    ("POST", "/api/v1/partners/00000000-0000-0000-0000-000000000000/checks/vies"),
]


def call(client: TestClient, method: str, path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.request(
        method, path, headers=headers, json={"vat_number": "ATU12345678"}
    )


def assert_401(response, code: str) -> None:
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["message"]
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_missing_token_gives_401(
    anonymous_client: TestClient, method: str, path: str
) -> None:
    assert_401(call(anonymous_client, method, path), "not_authenticated")


def test_valid_token_is_accepted(anonymous_client: TestClient, tokens) -> None:
    response = call(anonymous_client, "GET", "/api/v1/me", tokens.make())

    assert response.status_code == 200
    assert response.json() == {
        "id": "user-1",
        "email": "anna@example.com",
        "name": "Anna Muster",
        "roles": [],
    }


def test_me_lists_realm_roles(anonymous_client: TestClient, tokens) -> None:
    token = tokens.make(
        extra={
            "realm_access": {"roles": ["org-admin", "default-roles-bizpartnercheck"]}
        }
    )

    response = call(anonymous_client, "GET", "/api/v1/me", token)

    assert response.json()["roles"] == ["default-roles-bizpartnercheck", "org-admin"]


@pytest.mark.parametrize(
    "realm_access",
    [None, "org-admin", {"roles": "org-admin"}, {"roles": [1, None]}, {}],
)
def test_malformed_roles_give_no_roles(
    anonymous_client: TestClient, tokens, realm_access
) -> None:
    token = tokens.make(extra={"realm_access": realm_access})

    response = call(anonymous_client, "GET", "/api/v1/me", token)

    assert response.status_code == 200
    assert response.json()["roles"] == []


def test_health_needs_no_token(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/health").status_code == 200


def test_expired_token(anonymous_client: TestClient, tokens) -> None:
    token = tokens.make(
        expires_in=-120
    )  # expired 2 minutes ago, beyond the 30 s tolerance

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "token_expired")


def test_small_clock_difference_is_tolerated(
    anonymous_client: TestClient, tokens
) -> None:
    token = tokens.make(expires_in=-10)  # 10 s "expired": within the tolerance

    assert call(anonymous_client, "GET", "/api/v1/me", token).status_code == 200


def test_token_signed_with_another_key(anonymous_client: TestClient, tokens) -> None:
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = tokens.make(key=attacker_key)

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "invalid_token")


def test_token_with_unknown_key_id(anonymous_client: TestClient, tokens) -> None:
    assert_401(
        call(anonymous_client, "GET", "/api/v1/me", tokens.make(kid="unknown")),
        "invalid_token",
    )


def test_token_from_another_issuer(anonymous_client: TestClient, tokens) -> None:
    token = tokens.make(issuer="http://evil.test/realms/bizpartnercheck")

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "invalid_token")


def test_token_for_another_audience(anonymous_client: TestClient, tokens) -> None:
    token = tokens.make(audience="account")

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "invalid_token")


def test_audience_in_a_list_is_accepted(anonymous_client: TestClient, tokens) -> None:
    # Keycloak often sends several audiences, e.g. ["bizpartnercheck-api", "account"].
    token = tokens.make(audience=["bizpartnercheck-api", "account"])

    assert call(anonymous_client, "GET", "/api/v1/me", token).status_code == 200


def test_id_token_is_not_an_access_token(anonymous_client: TestClient, tokens) -> None:
    token = tokens.make(typ="ID")

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "invalid_token")


@pytest.mark.parametrize("claim", ["exp", "sub", "iat", "iss", "aud"])
def test_required_claims(anonymous_client: TestClient, tokens, claim: str) -> None:
    assert_401(
        call(anonymous_client, "GET", "/api/v1/me", tokens.make(omit=(claim,))),
        "invalid_token",
    )


def test_refresh_token_is_not_an_access_token(
    anonymous_client: TestClient, tokens
) -> None:
    assert_401(
        call(anonymous_client, "GET", "/api/v1/me", tokens.make(typ="Refresh")),
        "invalid_token",
    )


@pytest.mark.parametrize("claim", ["iat", "nbf"])
def test_token_from_the_future(
    anonymous_client: TestClient, tokens, claim: str
) -> None:
    future = int(time.time()) + 300
    token = tokens.make(extra={claim: future}, expires_in=900)

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "invalid_token")


def test_unsigned_token_is_rejected(anonymous_client: TestClient, tokens) -> None:
    # alg "none" with our key ID, so the token reaches the algorithm check in jwt.decode.
    claims = jwt.decode(tokens.make(), options={"verify_signature": False})
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": "test-key"})
    signature_removed = tokens.make().rsplit(".", 1)[0] + "."

    assert_401(call(anonymous_client, "GET", "/api/v1/me", unsigned), "invalid_token")
    assert_401(
        call(anonymous_client, "GET", "/api/v1/me", signature_removed), "invalid_token"
    )


def test_symmetric_algorithm_is_rejected(anonymous_client: TestClient, tokens) -> None:
    # Classic attack: sign with HS256 using the public key as secret.
    token = tokens.make(
        key="some-shared-secret-of-at-least-32-bytes!!", algorithm="HS256"
    )

    assert_401(call(anonymous_client, "GET", "/api/v1/me", token), "invalid_token")


@pytest.mark.parametrize("value", ["not-a-jwt", "a.b.c", ""])
def test_garbage_token(anonymous_client: TestClient, value: str) -> None:
    response = call(anonymous_client, "GET", "/api/v1/me", value)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"invalid_token", "not_authenticated"}


def test_other_auth_scheme_is_not_accepted(
    anonymous_client: TestClient, tokens
) -> None:
    response = anonymous_client.get(
        "/api/v1/me", headers={"Authorization": f"Basic {tokens.make()}"}
    )

    assert_401(response, "not_authenticated")


def test_keycloak_unreachable_gives_503(anonymous_client: TestClient, tokens) -> None:
    def keys_unavailable(_token: str):
        raise jwt.PyJWKClientConnectionError("connection refused")

    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        "http://keycloak.test/realms/bizpartnercheck",
        "bizpartnercheck-api",
        keys_unavailable,
    )

    response = call(anonymous_client, "GET", "/api/v1/me", tokens.make())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "auth_unavailable"


def test_verifier_raises_auth_unavailable_directly(tokens) -> None:
    def keys_unavailable(_token: str):
        raise jwt.PyJWKClientConnectionError("timeout")

    verifier = TokenVerifier("i", "a", keys_unavailable)

    with pytest.raises(AuthUnavailable):
        verifier.verify(tokens.make())


def test_signed_in_user_can_use_the_api(client: TestClient) -> None:
    # The normal `client` fixture sends a valid token: the existing API keeps working.
    assert (
        client.post("/api/v1/partners", json={"vat_number": "ATU12345678"}).status_code
        == 201
    )
    assert client.get("/api/v1/partners").status_code == 200


# --- No token: nothing about the API is revealed -------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/does-not-exist", None),
        ("DELETE", "/api/v1/partners", None),
        ("POST", "/api/v1/partners", "{not json"),
        ("GET", "/api/v1", None),
    ],
)
def test_without_token_every_api_path_gives_401(
    anonymous_client: TestClient, method: str, path: str, body: str | None
) -> None:
    response = anonymous_client.request(
        method, path, content=body, headers={"Content-Type": "application/json"}
    )

    assert_401(response, "not_authenticated")


def test_unknown_path_and_wrong_method_use_the_error_format(client: TestClient) -> None:
    not_found = client.get("/api/v1/does-not-exist")
    wrong_method = client.delete("/api/v1/partners")

    assert not_found.status_code == 404
    assert not_found.json()["detail"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["detail"]["code"] == "method_not_allowed"


# --- The real key lookup (PyJWKClient) against a small local JWKS server --------------


class _JwksServer:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.body, self.content_type = body, content_type
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", server.content_type)
                self.send_header("Content-Length", str(len(server.body)))
                self.end_headers()
                self.wfile.write(server.body)

            def log_message(self, *_args) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/certs"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def jwks_server() -> Iterator[type[_JwksServer]]:
    servers: list[_JwksServer] = []

    def start(body: bytes, content_type: str = "application/json") -> _JwksServer:
        server = _JwksServer(body, content_type)
        servers.append(server)
        return server

    yield start  # type: ignore[misc]
    for server in servers:
        server.close()


def _jwks_of(tokens) -> bytes:
    jwk = json.loads(
        jwt.algorithms.RSAAlgorithm.to_jwk(tokens.private_key.public_key())
    )
    jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    return json.dumps({"keys": [jwk]}).encode()


def _verifier(url: str) -> TokenVerifier:
    return TokenVerifier(
        "http://keycloak.test/realms/bizpartnercheck",
        "bizpartnercheck-api",
        jwks_key_resolver(url),
    )


def test_real_key_lookup_accepts_a_valid_token(jwks_server, tokens) -> None:
    server = jwks_server(_jwks_of(tokens))

    user = _verifier(server.url).verify(tokens.make())

    assert user.id == "user-1"


def test_real_key_lookup_rejects_an_unknown_key_id(jwks_server, tokens) -> None:
    server = jwks_server(_jwks_of(tokens))

    with pytest.raises(Exception) as caught:
        _verifier(server.url).verify(tokens.make(kid="other-key"))

    assert caught.type.__name__ == "TokenError"


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b'{"keys": []}', "application/json"),
        (b"<html>Keycloak is starting</html>", "text/html"),
        (
            b'{"keys": [{"kty": "oct", "k": "c2VjcmV0", "kid": "test-key"}]}',
            "application/json",
        ),
    ],
)
def test_broken_key_set_gives_503(
    anonymous_client: TestClient, jwks_server, tokens, body: bytes, content_type: str
) -> None:
    server = jwks_server(body, content_type)
    app.dependency_overrides[get_token_verifier] = lambda: _verifier(server.url)

    response = call(anonymous_client, "GET", "/api/v1/me", tokens.make())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "auth_unavailable"


def test_unreachable_key_server_gives_503(anonymous_client: TestClient, tokens) -> None:
    app.dependency_overrides[get_token_verifier] = lambda: _verifier(
        "http://127.0.0.1:9/certs"
    )

    response = call(anonymous_client, "GET", "/api/v1/me", tokens.make())

    assert response.status_code == 503
