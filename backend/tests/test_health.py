from unittest.mock import AsyncMock, patch

import psycopg
from fastapi.testclient import TestClient

from app.main import app


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
