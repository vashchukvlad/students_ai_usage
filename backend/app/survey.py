"""Validated, versioned CSV imports and authenticated survey analytics."""

import argparse
import asyncio
import csv
import hashlib
import io
import math
import os
import re
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.auth import User, current_user

SOURCE_URL = (
    "https://www.kaggle.com/datasets/ranaghulamnabi/"
    "ai-usage-and-student-academic-performance-analysis"
)
DEFAULT_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "ai_impact_on_students.csv"
)
MAX_ROWS = 100_000
MAX_BYTES = 50 * 1024 * 1024
MISSING = {"", "na", "n/a", "null", "none", "nan"}
NUMERIC_COLUMNS = {
    "Pre_Semester_GPA",
    "Weekly_GenAI_Hours",
    "Tool_Diversity",
    "Traditional_Study_Hours",
    "Perceived_AI_Dependency",
    "Anxiety_Level_During_Exams",
    "Post_Semester_GPA",
    "Skill_Retention_Score",
}
CATEGORY_COLUMNS = {
    "Major_Category",
    "Year_of_Study",
    "Primary_Use_Case",
    "Prompt_Engineering_Skill",
    "Paid_Subscription",
    "Institutional_Policy",
    "Burnout_Risk_Level",
}
REQUIRED_COLUMNS = NUMERIC_COLUMNS | CATEGORY_COLUMNS | {"Student_ID"}
router = APIRouter(prefix="/api", tags=["survey"])


def label(name: str) -> str:
    return re.sub(r"[_\s]+", " ", name).strip()


def parse_csv(path: Path) -> tuple[str, list[dict], list[dict]]:
    """Infer types from every non-missing value, never a small sample."""
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("CSV must be at most 50 MiB")
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(
        io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True
    )
    names = reader.fieldnames
    if not names or len(names) > 100 or any(not n.strip() for n in names):
        raise ValueError("CSV needs 1–100 non-empty column names")
    if len(set(names)) != len(names):
        raise ValueError("CSV column names must be unique")
    missing = REQUIRED_COLUMNS - set(names)
    if missing:
        raise ValueError(f"Missing dataset columns: {', '.join(sorted(missing))}")
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(
                f"Inconsistent CSV field count near line {reader.line_num}"
            )
        if all(not value.strip() for value in row.values()):
            continue
        rows.append(
            {
                k: None if v.strip().lower() in MISSING else v.strip()
                for k, v in row.items()
            }
        )
        if len(rows) > MAX_ROWS:
            raise ValueError(f"CSV must contain at most {MAX_ROWS:,} rows")
    if not rows:
        raise ValueError("CSV has no survey responses")
    identifiers = [row["Student_ID"] for row in rows]
    if None in identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError("Student_ID must be non-empty and unique")
    columns = []
    for name in names:
        values = [row[name] for row in rows if row[name] is not None]
        identifier = bool(re.search(r"(^|[_\s])id$", name, re.IGNORECASE))
        numeric = (bool(values) or name in NUMERIC_COLUMNS) and not identifier
        try:
            numbers = [float(value) for value in values]
            numeric = numeric and all(math.isfinite(value) for value in numbers)
        except ValueError:
            numeric = False
        if name in NUMERIC_COLUMNS and not numeric:
            raise ValueError(f"{name} must contain finite numeric values or blanks")
        if name in CATEGORY_COLUMNS and numeric:
            raise ValueError(f"{name} must contain category labels")
        distinct = sorted(set(values))
        kind = (
            "number"
            if numeric
            else "category"
            if len(distinct) <= 100 and not identifier
            else "text"
        )
        if numeric:
            for row in rows:
                if row[name] is not None:
                    row[name] = float(row[name])
                    if (
                        name in {"Pre_Semester_GPA", "Post_Semester_GPA"}
                        and not 0 <= row[name] <= 4
                    ):
                        raise ValueError(f"{name} must be between 0 and 4")
                    if (
                        name in {"Weekly_GenAI_Hours", "Traditional_Study_Hours"}
                        and not 0 <= row[name] <= 168
                    ):
                        raise ValueError(f"{name} must be between 0 and 168 hours")
        columns.append(
            {
                "name": name,
                "label": label(name),
                "kind": kind,
                "values": distinct if kind == "category" else [],
            }
        )
    return checksum, columns, rows


async def initialize_survey(database_url: str):
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        # Shared by schema initialization and import for concurrent worker starts.
        await connection.execute("SELECT pg_advisory_xact_lock(74216001)")
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS survey_dataset (
                id SMALLINT PRIMARY KEY CHECK (id = 1),
                checksum TEXT NOT NULL,
                source_url TEXT NOT NULL,
                filename TEXT NOT NULL,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                columns JSONB NOT NULL,
                row_count INTEGER NOT NULL CHECK (row_count > 0)
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS survey_responses (
                row_number INTEGER PRIMARY KEY,
                data JSONB NOT NULL
            )
        """)


async def import_csv(database_url: str, path: Path) -> dict:
    # Validate before touching live data. Parsing is off the event loop.
    checksum, columns, rows = await asyncio.to_thread(parse_csv, path)
    await initialize_survey(database_url)
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute("SELECT pg_advisory_xact_lock(74216001)")
        cursor = await connection.execute(
            "SELECT checksum FROM survey_dataset WHERE id = 1"
        )
        existing = await cursor.fetchone()
        if existing and existing[0] == checksum:
            return {"status": "unchanged", "rows": len(rows), "checksum": checksum}
        # Atomic replacement: other readers see either complete version.
        await connection.execute("DELETE FROM survey_responses")
        async with (
            connection.cursor() as cursor,
            cursor.copy("COPY survey_responses (row_number, data) FROM STDIN") as copy,
        ):
            for number, row in enumerate(rows, 1):
                await copy.write_row((number, Jsonb(row)))
        await connection.execute(
            "INSERT INTO survey_dataset (id, checksum, source_url, filename, columns, row_count) "
            "VALUES (1, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
            "checksum = EXCLUDED.checksum, source_url = EXCLUDED.source_url, "
            "filename = EXCLUDED.filename, columns = EXCLUDED.columns, "
            "row_count = EXCLUDED.row_count, imported_at = now()",
            (checksum, SOURCE_URL, path.name, Jsonb(columns), len(rows)),
        )
    return {"status": "imported", "rows": len(rows), "checksum": checksum}


def choose(columns: list[dict], kind: str, preferred: tuple[str, ...]) -> str | None:
    available = [column["name"] for column in columns if column["kind"] == kind]
    return next(
        (name for term in preferred for name in available if term in name.lower()),
        available[0] if available else None,
    )


@router.get("/dashboard")
async def dashboard(
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    metric: str | None = None,
    group_by: str | None = None,
    major: str | None = None,
    year: str | None = None,
    burnout: str | None = None,
    page: Annotated[int, Query(ge=1, le=4000)] = 1,
):
    response.headers["Cache-Control"] = "no-store"
    try:
        async with await psycopg.AsyncConnection.connect(
            request.app.state.database_url, row_factory=dict_row, connect_timeout=3
        ) as connection:
            # Keep metadata, aggregates and rows on the same dataset snapshot.
            await connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            cursor = await connection.execute(
                "SELECT * FROM survey_dataset WHERE id = 1"
            )
            dataset = await cursor.fetchone()
            if not dataset:
                return {"status": "empty", "source_url": SOURCE_URL}
            columns = dataset["columns"]
            numeric = {
                column["name"] for column in columns if column["kind"] == "number"
            }
            categorical = {
                column["name"] for column in columns if column["kind"] == "category"
            }
            metric = (
                metric
                if metric is not None
                else choose(
                    columns,
                    "number",
                    ("weekly_genai_hours", "post_semester_gpa", "gpa", "score"),
                )
            )
            group_by = (
                group_by
                if group_by is not None
                else choose(columns, "category", ("major_category", "year_of_study"))
            )
            if metric is not None and metric not in numeric:
                raise HTTPException(422, "Unknown numeric metric")
            if group_by is not None and group_by not in categorical:
                raise HTTPException(422, "Unknown category")
            clauses, params_list = [], []
            definitions = {column["name"]: column for column in columns}
            for name, value in (
                ("Major_Category", major),
                ("Year_of_Study", year),
                ("Burnout_Risk_Level", burnout),
            ):
                if value is not None:
                    if value not in definitions[name]["values"]:
                        raise HTTPException(422, f"Unknown value for {name}")
                    clauses.append("data ->> %s = %s")
                    params_list.extend((name, value))
            # Both column names and values are SQL parameters.
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params = tuple(params_list)
            cursor = await connection.execute(
                "SELECT count(*) AS count, count(data ->> %s) AS measured, "
                "avg((data ->> %s)::double precision) AS average, "
                "min((data ->> %s)::double precision) AS minimum, "
                "max((data ->> %s)::double precision) AS maximum, "
                "avg((data ->> 'Weekly_GenAI_Hours')::double precision) AS ai_hours, "
                "avg((data ->> 'Pre_Semester_GPA')::double precision) AS pre_gpa, "
                "avg((data ->> 'Post_Semester_GPA')::double precision) AS post_gpa, "
                "avg((data ->> 'Post_Semester_GPA')::double precision - "
                "(data ->> 'Pre_Semester_GPA')::double precision) AS gpa_change, "
                "count(*) FILTER (WHERE data ->> 'Burnout_Risk_Level' = 'High') AS high_burnout "
                "FROM survey_responses" + where,
                (metric, metric, metric, metric, *params),
            )
            summary = await cursor.fetchone()
            groups = []
            if group_by:
                cursor = await connection.execute(
                    "SELECT data ->> %s AS name, count(*) AS count, "
                    "avg((data ->> %s)::double precision) AS average, "
                    "avg((data ->> 'Weekly_GenAI_Hours')::double precision) AS ai_hours, "
                    "avg((data ->> 'Pre_Semester_GPA')::double precision) AS pre_gpa, "
                    "avg((data ->> 'Post_Semester_GPA')::double precision) AS post_gpa "
                    "FROM survey_responses"
                    + where
                    + " GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 100",
                    (group_by, metric, *params),
                )
                groups = await cursor.fetchall()
            histogram = []
            low, high = summary["minimum"], summary["maximum"]
            if metric and low is not None:
                # Equal-width, inclusive edge bins; constant data uses one bin.
                width = (high - low) / 10 if high != low else 1
                cursor = await connection.execute(
                    "SELECT least(9, greatest(0, floor(((data ->> %s)::double precision - %s) / %s)))::int AS bin, "
                    "count(*) AS count FROM survey_responses"
                    + where
                    + (" AND " if where else " WHERE ")
                    + "data ->> %s IS NOT NULL GROUP BY 1 ORDER BY 1",
                    (metric, low, width, *params, metric),
                )
                counts = {row["bin"]: row["count"] for row in await cursor.fetchall()}
                histogram = [
                    {
                        "from": low + i * width,
                        "to": high if high == low else low + (i + 1) * width,
                        "count": counts.get(i, 0),
                    }
                    for i in range(1 if high == low else 10)
                ]
            pages = max(1, math.ceil(summary["count"] / 25))
            page = min(page, pages)
            cursor = await connection.execute(
                "SELECT row_number, data FROM survey_responses"
                + where
                + " ORDER BY row_number LIMIT 25 OFFSET %s",
                (*params, (page - 1) * 25),
            )
            rows = await cursor.fetchall()
            return {
                "status": "ready",
                "dataset": dataset,
                "metric": metric,
                "group_by": group_by,
                "summary": summary,
                "groups": groups,
                "histogram": histogram,
                "rows": rows,
                "page": page,
                "pages": pages,
            }
    except psycopg.Error as error:
        raise HTTPException(
            503, "Survey database unavailable. Please try again."
        ) from error


def main():
    parser = argparse.ArgumentParser(
        description="Validate and atomically import a survey CSV"
    )
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("Set DATABASE_URL before importing")
    try:
        result = asyncio.run(import_csv(database_url, args.csv))
    except (ValueError, OSError, UnicodeError, csv.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    print(
        f"{result['status']}: {result['rows']:,} responses; SHA-256 {result['checksum']}"
    )


if __name__ == "__main__":
    main()
