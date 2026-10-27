import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app

SECRET = "integration-test-signing-secret-at-least-32-characters"


@pytest.fixture
def client(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    with TestClient(app) as client:
        yield client


def register(client):
    email = f"student-{uuid4().hex}@example.com"
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Alex Morgan",
            "email": email,
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), email


def authorization(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_register_login_logout(client):
    session, email = register(client)
    cookie = client.cookies.get("refresh_token")
    assert cookie and cookie not in session["access_token"]
    response = client.get("/api/auth/me", headers=authorization(session))
    assert response.status_code == 200
    assert response.json()["email"] == email
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        hashed = connection.execute(
            "SELECT password_hash FROM users WHERE email=%s", (email,)
        ).fetchone()[0]
    assert hashed.startswith("$argon2id$")
    assert "correct-horse-battery" not in hashed
    assert client.post("/api/auth/logout").status_code == 204
    assert not client.cookies.get("refresh_token")
    assert client.get("/api/auth/me", headers=authorization(session)).status_code == 401
    assert client.post("/api/auth/refresh").status_code == 401
    response = client.post(
        "/api/auth/login",
        json={"email": email.upper(), "password": "correct-horse-battery"},
    )
    assert response.status_code == 200
    assert (
        client.get("/api/auth/me", headers=authorization(response.json())).status_code
        == 200
    )
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/logout").status_code == 204


def test_refresh_rotates_and_rejects_replay(client):
    original, _ = register(client)
    old = client.cookies.get("refresh_token")
    response = client.post("/api/auth/refresh")
    assert response.status_code == 200
    new = client.cookies.get("refresh_token")
    assert new != old
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    assert "refresh_token" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.get("/api/auth/me", headers=authorization(response.json())).status_code
        == 200
    )
    client.cookies.clear()
    assert (
        client.post(
            "/api/auth/refresh", headers={"Cookie": f"refresh_token={old}"}
        ).status_code
        == 401
    )
    client.cookies.set("refresh_token", new, path="/api/auth")
    assert client.post("/api/auth/logout").status_code == 204
    assert (
        client.get("/api/auth/me", headers=authorization(original)).status_code == 401
    )


def test_invalid_password_duplicate_and_validation(client):
    _, email = register(client)
    for account in [email, "unknown@example.com"]:
        response = client.post(
            "/api/auth/login", json={"email": account, "password": "wrong-password"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    assert (
        client.post(
            "/api/auth/register",
            json={"email": email, "name": "Alex", "password": "another-password"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "bad", "name": "Alex", "password": "short"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/register",
            json={
                "email": "valid@example.com",
                "name": "  ",
                "password": "valid-password",
            },
        ).status_code
        == 422
    )


def test_invalid_expired_and_forged_access_tokens(client):
    session, _ = register(client)
    claims = jwt.decode(
        session["access_token"],
        SECRET,
        algorithms=["HS256"],
        audience="students-ai-usage-api",
    )
    expired = {**claims, "exp": datetime.now(UTC) - timedelta(seconds=1)}
    for token in [
        "invalid",
        jwt.encode(expired, SECRET, algorithm="HS256"),
        jwt.encode(
            claims, "wrong-secret-that-is-long-enough-for-hmac", algorithm="HS256"
        ),
    ]:
        assert (
            client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )
    assert client.get("/api/auth/me").status_code == 401
    # A validly signed token still needs the correct token purpose and live session.
    for changed in [{"type": "refresh"}, {"sid": str(uuid4())}, {"sub": str(uuid4())}]:
        token = jwt.encode({**claims, **changed}, SECRET, algorithm="HS256")
        assert (
            client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )


def test_expired_refresh_and_cross_origin_requests(client):
    session, _ = register(client)
    for endpoint in ["refresh", "logout", "register", "login"]:
        assert (
            client.post(
                f"/api/auth/{endpoint}", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE auth_sessions SET expires_at = now() - interval '1 second' WHERE user_id = %s",
            (session["user"]["id"],),
        )
    assert client.post("/api/auth/refresh").status_code == 401
    assert client.get("/api/auth/me", headers=authorization(session)).status_code == 401
