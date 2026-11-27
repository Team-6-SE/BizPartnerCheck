"""SCRUM-49: permissions, organisation isolation, last admin, invitations."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.errors import api_error
from app.main import app
from app.users.directory import get_directory

ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.uuid4()
ADMIN_ID = str(uuid.uuid4())
MEMBER_ID = str(uuid.uuid4())
FOREIGN_ID = str(uuid.uuid4())


class FakeDirectory:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {
            ADMIN_ID: self.make_user(ADMIN_ID, ORG, "admin@example.com", "org-admin"),
            MEMBER_ID: self.make_user(MEMBER_ID, ORG, "member@example.com", "checker"),
            FOREIGN_ID: self.make_user(FOREIGN_ID, OTHER, "foreign@example.com", "org-admin"),
        }
        self.sent: list[str] = []

    @staticmethod
    def make_user(id_: str, org: uuid.UUID, email: str, role: str) -> dict[str, Any]:
        return {
            "id": id_, "username": email, "email": email,
            "firstName": "Test", "lastName": "User", "enabled": True,
            "emailVerified": True, "attributes": {"organization_id": [str(org)]},
            "_role": role,
        }

    def list_users(self, org: uuid.UUID) -> list[dict[str, Any]]:
        return [u for u in self.users.values() if u["attributes"]["organization_id"] == [str(org)]]

    def get_user(self, id_: uuid.UUID, org: uuid.UUID) -> dict[str, Any]:
        u = self.users.get(str(id_))
        if u is None or u["attributes"]["organization_id"] != [str(org)]:
            raise api_error(404, "user_not_found", "User not found.")
        return u

    def assigned_roles(self, id_: str) -> set[str]:
        return {self.users[id_]["_role"]}

    def invite(self, email: str, name: str, org: uuid.UUID, role: str) -> dict[str, Any]:
        id_ = str(uuid.uuid4())
        u = self.make_user(id_, org, email, role)
        u["emailVerified"] = False
        self.users[id_] = u
        self.sent.append(id_)
        return u

    def update_role(self, id_: str, role: str) -> None:
        self.users[id_]["_role"] = role

    def set_enabled(self, id_: str, enabled: bool) -> None:
        self.users[id_]["enabled"] = enabled

    def send_invitation(self, id_: str) -> None:
        self.sent.append(id_)

    def delete(self, id_: str) -> None:
        del self.users[id_]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin(tokens: Any) -> dict[str, str]:
    return _auth(tokens.make(sub=ADMIN_ID, extra={"realm_access": {"roles": ["org-admin"]}}))


def test_checker_cannot_list_or_invite(anonymous_client: TestClient, tokens: Any) -> None:
    headers = _auth(tokens.make())
    assert anonymous_client.get("/api/v1/users", headers=headers).status_code == 403
    response = anonymous_client.post("/api/v1/users/invitations", headers=headers,
        json={"email": "new@example.com", "name": "New One", "role": "checker"})
    assert response.status_code == 403


def test_users_scoped_to_organisation(anonymous_client: TestClient, tokens: Any) -> None:
    fake = FakeDirectory()
    app.dependency_overrides[get_directory] = lambda: fake
    response = anonymous_client.get("/api/v1/users", headers=_admin(tokens))
    assert response.status_code == 200
    assert {u["id"] for u in response.json()} == {ADMIN_ID, MEMBER_ID}
    response = anonymous_client.delete(f"/api/v1/users/{FOREIGN_ID}", headers=_admin(tokens))
    assert response.status_code == 404


def test_last_admin_cannot_be_removed_or_demoted(anonymous_client: TestClient, tokens: Any, monkeypatch: Any) -> None:
    from app.users import router as users_router

    monkeypatch.setattr(users_router, "_scoped_lock", lambda _db, _org: None)
    fake = FakeDirectory()
    app.dependency_overrides[get_directory] = lambda: fake
    headers = _admin(tokens)
    for method, path, body in [
        ("PATCH", f"/api/v1/users/{ADMIN_ID}/role", {"role": "reviewer"}),
        ("PATCH", f"/api/v1/users/{ADMIN_ID}/status", {"enabled": False}),
        ("DELETE", f"/api/v1/users/{ADMIN_ID}", None),
    ]:
        resp = anonymous_client.request(method, path, headers=headers, json=body)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "last_admin"


def test_invite_and_change_roles(anonymous_client: TestClient, tokens: Any, monkeypatch: Any) -> None:
    from app.users import router as users_router

    monkeypatch.setattr(users_router, "_scoped_lock", lambda _db, _org: None)
    fake = FakeDirectory()
    app.dependency_overrides[get_directory] = lambda: fake
    headers = _admin(tokens)
    response = anonymous_client.post("/api/v1/users/invitations", headers=headers,
        json={"email": "new@example.com", "name": "New Colleague", "role": "reviewer"})
    assert response.status_code == 201
    assert response.json()["role"] == "reviewer"
    id_ = response.json()["id"]
    assert id_ in fake.sent
    response = anonymous_client.patch(f"/api/v1/users/{id_}/role", headers=headers,
        json={"role": "checker"})
    assert response.status_code == 200
    assert response.json()["role"] == "checker"


def test_reviewer_cannot_modify_partners(anonymous_client: TestClient, tokens: Any) -> None:
    headers = _auth(tokens.make(extra={"realm_access": {"roles": ["reviewer"]}}))
    response = anonymous_client.post("/api/v1/partners", headers=headers,
        json={"vat_number": "ATU12345678"})
    assert response.status_code == 403
