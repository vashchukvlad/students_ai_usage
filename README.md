# Student AI Usage Dashboard

A full-stack dashboard for exploring how students use artificial intelligence and how AI usage relates to their academic performance, well-being, and other aspects of student life.

The goal is to turn student survey data into clear, interactive visualizations that help identify trends, patterns, and potential correlations. The dashboard is intended for exploratory analysis; correlations do not necessarily imply causation.

## Tech Stack

- **Backend:** Python, FastAPI, PostgreSQL
- **Frontend:** React, TypeScript, Vite
- **Development & tooling:** Docker, uv, Ruff

## Planned Features

- Visualize AI usage patterns among students.
- Explore relationships between AI usage, academic performance, and well-being.
- Filter and compare data across different student groups.
- Display key metrics and interactive charts.

## Project Status

🚧 **Early development** — the API, frontend, and database development setup are initialized. Survey features are not implemented yet.


## Quick start: everything in Docker

Requires Docker with Compose v2. From the repository root:

```sh
docker compose up --build --wait
```

Open the dashboard at `http://localhost:8080`, API documentation at
`http://localhost:8000/docs`, and API/database readiness at
`http://localhost:8000/api/health`. The frontend routes `/api` requests to FastAPI.
The API returns HTTP 503 when PostgreSQL is unavailable.

## Local backend and frontend, database in Docker

Requires Python 3.12+, uv, and Node.js 22.12+ (Node.js 24 LTS recommended).
From the repository root:

```sh
docker compose -f docker-compose.db.yml up -d --wait
cd backend
uv sync --frozen
DATABASE_URL=postgresql://students:students_dev@127.0.0.1:5432/students_ai_usage uv run uvicorn app.main:app --reload
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to the local backend on port
8000, so both development modes use the same frontend API paths.

## Configuration and data

Both Compose configurations share the same PostgreSQL service settings and named
volume. Run one mode at a time; stop the full stack before switching to local
processes to release port 8000. PostgreSQL is bound to loopback on port 5432.

Optionally copy `.env.example` to `.env` in the repository root to override
Compose database settings. The defaults are for local development only.
For local backend processes, set `DATABASE_URL` explicitly to match your database
credentials and `POSTGRES_PORT`; Compose's `.env` is not automatically loaded by
the backend. URL-encode special characters in database credentials used in URLs.
Existing database volumes retain their initial credentials even if `.env` changes.

Stop the selected mode without deleting data:

```sh
docker compose down
# Or, for database-only mode:
docker compose -f docker-compose.db.yml down
```

Add `--volumes` only when you deliberately want to delete local database data.
The frontend container serves a compiled build through nginx; rebuild after source
changes. Local Vite and Uvicorn processes support hot reload.

## Checks

```sh
cd backend
uv sync --frozen
uv run pytest
uv run ruff check .
cd ../frontend
npm ci
npm run build
```

With either mode running, verify the database-backed health endpoint:

```sh
curl --fail http://localhost:8000/api/health
# Expected: {"status":"ok","database":"ok"}
```

The starter page reports API/database connectivity. No survey data or migrations
are required yet.
