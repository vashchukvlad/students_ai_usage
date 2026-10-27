from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def auth_setup(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "health-test-secret-that-is-long-enough")
    monkeypatch.setattr("app.main.initialize_database", AsyncMock())
    monkeypatch.setattr("app.main.initialize_survey", AsyncMock())
    monkeypatch.delenv("SURVEY_CSV_PATH", raising=False)
    monkeypatch.setattr("app.main.DEFAULT_CSV", Path("/nonexistent.csv"))


def test_health_checks_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    connection = AsyncMock()
    cursor = AsyncMock()
    connection.__aenter__.return_value = connection
    connection.cursor = lambda: cursor
    cursor.__aenter__.return_value = cursor
    cursor.fetchone.return_value = (1,)
    with (
        patch("app.main.psycopg.AsyncConnection.connect", return_value=connection),
        TestClient(app) as client,
    ):
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    cursor.execute.assert_awaited_once_with("SELECT 1")


def test_health_reports_database_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    with (
        patch(
            "app.main.psycopg.AsyncConnection.connect",
            side_effect=psycopg.OperationalError("connection failed"),
        ),
        TestClient(app) as client,
    ):
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_dashboard_database_failure_during_authentication(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    token = jwt.encode(
        {
            "sub": "student",
            "sid": "session",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=1),
            "iss": "students-ai-usage",
            "aud": "students-ai-usage-api",
        },
        "health-test-secret-that-is-long-enough",
        algorithm="HS256",
    )
    with (
        patch(
            "app.main.psycopg.AsyncConnection.connect",
            side_effect=psycopg.OperationalError("connection failed"),
        ),
        TestClient(app) as client,
    ):
        response = client.get(
            "/api/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Database unavailable. Please try again."}
