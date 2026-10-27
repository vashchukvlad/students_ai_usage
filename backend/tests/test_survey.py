import asyncio
import csv
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.main import app
from app.survey import DEFAULT_CSV, import_csv, parse_csv


@pytest.fixture
def source_rows():
    with DEFAULT_CSV.open(newline="") as file:
        rows = list(csv.DictReader(file))[:3]
    for i, row in enumerate(rows):
        row.update(
            Student_ID=str(i + 1),
            Major_Category="STEM" if i < 2 else "Arts",
            Year_of_Study="Junior" if i == 0 else "Senior",
            Pre_Semester_GPA=str(2 + i / 2),
            Post_Semester_GPA=str(2.5 + i / 2),
            Weekly_GenAI_Hours=str(i * 10),
            Burnout_Risk_Level="High" if i == 0 else "Low",
        )
    return rows


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_bundled_dataset_is_valid():
    checksum, columns, rows = parse_csv(DEFAULT_CSV)
    assert len(rows) == 50_000
    assert len(columns) == 16
    assert len(checksum) == 64
    assert next(c for c in columns if c["name"] == "Student_ID")["kind"] == "text"
    assert (
        next(c for c in columns if c["name"] == "Post_Semester_GPA")["kind"] == "number"
    )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"Weekly_GenAI_Hours": "Infinity"}, "finite numeric"),
        ({"Post_Semester_GPA": "broken"}, "finite numeric"),
        ({"Post_Semester_GPA": "4.5"}, "between 0 and 4"),
        ({"Weekly_GenAI_Hours": "-2"}, "between 0 and 168"),
        ({"Student_ID": ""}, "non-empty and unique"),
    ],
)
def test_rejects_invalid_measurements(tmp_path, source_rows, change, match):
    source_rows[0].update(change)
    path = write_csv(tmp_path / "bad.csv", source_rows)
    with pytest.raises(ValueError, match=match):
        parse_csv(path)


def test_missing_and_zero_are_distinct(tmp_path, source_rows):
    source_rows[0]["Post_Semester_GPA"] = "N/A"
    source_rows[1]["Post_Semester_GPA"] = "0"
    _, _, rows = parse_csv(write_csv(tmp_path / "missing.csv", source_rows))
    assert rows[0]["Post_Semester_GPA"] is None
    assert rows[1]["Post_Semester_GPA"] == 0


def test_duplicate_ids_and_bad_shape(tmp_path, source_rows):
    source_rows[1]["Student_ID"] = source_rows[0]["Student_ID"]
    with pytest.raises(ValueError, match="unique"):
        parse_csv(write_csv(tmp_path / "duplicates.csv", source_rows))
    path = tmp_path / "shape.csv"
    path.write_text("Student_ID,Student_ID\n1,2\n")
    with pytest.raises(ValueError, match="unique"):
        parse_csv(path)
    path.write_text("Student_ID\n1\n")
    with pytest.raises(ValueError, match="Missing dataset columns"):
        parse_csv(path)
    path = write_csv(tmp_path / "truncated.csv", source_rows)
    with path.open("a") as file:
        file.write("truncated,row\n")
    with pytest.raises(ValueError, match="field count"):
        parse_csv(path)


@pytest.fixture
def database_url():
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    schema = "survey_test_" + uuid4().hex
    with psycopg.connect(base) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    yield make_conninfo(base, options=f"-c search_path={schema}")
    with psycopg.connect(base) as connection:
        connection.execute(
            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
        )


@pytest.fixture
def client(database_url, monkeypatch, tmp_path, source_rows):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv(
        "JWT_SECRET", "survey-test-signing-secret-at-least-32-characters"
    )
    monkeypatch.setenv(
        "SURVEY_CSV_PATH", str(write_csv(tmp_path / "source.csv", source_rows))
    )
    with TestClient(app) as client:
        yield client


def authenticate(client):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Survey Tester",
            "email": "survey@example.com",
            "password": "test-survey-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_dashboard_auth_aggregates_filters_and_pagination(client):
    assert client.get("/api/dashboard").status_code == 401
    headers = authenticate(client)
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["dataset"]["row_count"] == 3
    assert body["summary"]["ai_hours"] == 10
    assert body["summary"]["post_gpa"] == 3
    assert body["summary"]["gpa_change"] == 0.5
    assert body["summary"]["high_burnout"] == 1
    assert sum(group["count"] for group in body["groups"]) == 3
    assert sum(bin["count"] for bin in body["histogram"]) == 3
    assert body["rows"][0]["data"]["Student_ID"] == "1"
    # Filter values containing injection syntax are rejected, not interpolated.
    for query in [
        "metric=Student_ID",
        "group_by=unknown",
        "page=0",
        "major=' OR 1=1--",
    ]:
        assert client.get(f"/api/dashboard?{query}", headers=headers).status_code == 422
    filtered = client.get(
        "/api/dashboard?major=STEM&year=Junior&burnout=High&page=4000", headers=headers
    ).json()
    assert filtered["summary"]["count"] == 1
    assert filtered["page"] == 1
    assert filtered["histogram"] == [{"from": 0, "to": 0, "count": 1}]
    empty = client.get("/api/dashboard?major=Arts&year=Junior", headers=headers).json()
    assert empty["summary"]["count"] == 0
    assert empty["rows"] == [] and empty["histogram"] == []
    client.post("/api/auth/logout")
    assert client.get("/api/dashboard", headers=headers).status_code == 401


def test_import_idempotence_replacement_and_rollback(
    client, database_url, tmp_path, source_rows
):
    headers = authenticate(client)
    before = client.get("/api/dashboard", headers=headers).json()["dataset"]
    result = asyncio.run(import_csv(database_url, tmp_path / "source.csv"))
    assert result["status"] == "unchanged"
    assert (
        client.get("/api/dashboard", headers=headers).json()["dataset"]["imported_at"]
        == before["imported_at"]
    )
    # Force a database failure after DELETE, proving the previous snapshot survives.
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "ALTER TABLE survey_responses ADD CONSTRAINT fail_replacement CHECK (row_number < 4)"
        )
    extra = {**source_rows[0], "Student_ID": "4"}
    path = write_csv(tmp_path / "replacement.csv", [*source_rows, extra])
    with pytest.raises(psycopg.errors.CheckViolation):
        asyncio.run(import_csv(database_url, path))
    after = client.get("/api/dashboard", headers=headers).json()
    assert after["dataset"]["checksum"] == before["checksum"]
    assert after["summary"]["count"] == 3
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "ALTER TABLE survey_responses DROP CONSTRAINT fail_replacement"
        )
    assert asyncio.run(import_csv(database_url, path))["status"] == "imported"
    assert client.get("/api/dashboard", headers=headers).json()["summary"]["count"] == 4
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    source_rows[0]["Post_Semester_GPA"] = "broken"
    with pytest.raises(ValueError):
        asyncio.run(
            import_csv(database_url, write_csv(tmp_path / "invalid.csv", source_rows))
        )
    assert client.get("/api/dashboard", headers=headers).json()["summary"]["count"] == 4


def test_missing_data_and_empty_database(client, database_url, tmp_path, source_rows):
    headers = authenticate(client)
    for row in source_rows:
        row["Post_Semester_GPA"] = ""
        row["Weekly_GenAI_Hours"] = ""
    asyncio.run(
        import_csv(database_url, write_csv(tmp_path / "missing.csv", source_rows))
    )
    data = client.get("/api/dashboard", headers=headers).json()
    assert data["summary"]["post_gpa"] is None
    assert data["summary"]["gpa_change"] is None
    assert data["summary"]["measured"] == 0
    assert data["histogram"] == []
    with psycopg.connect(database_url) as connection:
        connection.execute("DELETE FROM survey_responses")
        connection.execute("DELETE FROM survey_dataset")
    assert client.get("/api/dashboard", headers=headers).json()["status"] == "empty"
