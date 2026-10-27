# Student AI Usage Dashboard

A full-stack dashboard for exploring how students use artificial intelligence and how AI usage relates to their academic performance, well-being, and other aspects of student life.

The goal is to turn student survey data into clear, interactive visualizations that help identify trends, patterns, and potential correlations. The dashboard is intended for exploratory analysis; correlations do not necessarily imply causation.

## Tech Stack

- **Backend:** Python, FastAPI, PostgreSQL
- **Frontend:** React, TypeScript, Vite
- **Development & tooling:** Docker, uv, Ruff

## Features

- Visualize AI usage patterns among students.
- Explore relationships between AI usage, academic performance, and well-being.
- Filter and compare data across different student groups.
- Display key metrics and interactive charts.

## Project Status

The authenticated dashboard is backed by the bundled student AI dataset: 50,000
records, automatic PostgreSQL seeding, interactive filters, GPA comparisons,
measurement distributions, and paginated survey records.

See [the feature walkthrough and screenshots](features_readme/kaggle-student-dashboard.md).


## Quick start: everything in Docker

Requires Docker with Compose v2. Before the first start, copy `.env.example` to
`.env` (keep your existing `.env` if present), generate a random signing key with
`openssl rand -hex 32`, and put it in `JWT_SECRET` in `.env`. Never commit this key.
The API requires a signing key of at least 32 characters and refuses to start
without one. Use a different key for each deployment.

From the repository root:

```sh
docker compose up --build --wait
```

Open the dashboard at `http://localhost:8080`, API documentation at
`http://localhost:8000/docs`, and API/database readiness at
`http://localhost:8000/api/health`. The frontend routes `/api` requests to FastAPI.
The API returns HTTP 503 when PostgreSQL is unavailable.

## Local backend and frontend, database in Docker

Requires Python 3.12+, uv, and Node.js 22.12+ (Node.js 24 LTS recommended).
Prepare `.env` with `JWT_SECRET` as described above, then from the repository root:

```sh
docker compose -f docker-compose.db.yml up -d --wait
cd backend
uv sync --frozen
DATABASE_URL=postgresql://students:students_dev@127.0.0.1:5432/students_ai_usage uv run uvicorn app.main:app --reload --env-file ../.env
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

You can also override Compose database settings in the root `.env`. The database
defaults are for local development only.
For local backend processes, load `JWT_SECRET` with `--env-file ../.env` and set
`DATABASE_URL` explicitly to match your database credentials and `POSTGRES_PORT`.
URL-encode special characters in database credentials used in URLs.
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
# Use a dedicated database for integration tests (never your development data).
# Create it once while the database service is running:
docker compose -f ../docker-compose.db.yml exec -T db createdb -U students students_auth_test
TEST_DATABASE_URL=postgresql://students:students_dev@127.0.0.1:5432/students_auth_test uv run pytest
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

The API initializes account/session tables and survey tables at startup, then
imports the bundled CSV before accepting requests. A matching SHA-256 skips writes.
The health endpoint remains public for container readiness. Database integration
tests are skipped when `TEST_DATABASE_URL` is unset; parser and health tests still
run. Survey integration tests create and remove isolated schemas in that dedicated
test database; never point them at a shared or production database.


## Authentication

The frontend supports account registration, sign-in, sign-out, session restoration
on reload, and automatic access-token refresh. After registration, sign-in, or
session restoration, the frontend opens the authenticated dashboard. Both profile and survey endpoints require a live session.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/auth/register` | Create an account with `name`, `email`, and `password`; sign in |
| `POST /api/auth/login` | Sign in with `email` and `password` |
| `POST /api/auth/refresh` | Rotate the refresh cookie and issue a new access JWT |
| `POST /api/auth/logout` | Revoke the current session and clear its cookie |
| `GET /api/auth/me` | Return the current user; requires `Authorization: Bearer <access_token>` |

Passwords use Argon2id hashing. Access JWTs expire after 15 minutes and stay only
in frontend memory, never localStorage. A random refresh token is stored in an
HttpOnly, SameSite=Strict cookie scoped to `/api/auth`; only its SHA-256 hash is
stored in PostgreSQL. Refresh tokens rotate atomically on use, expire after seven
days of inactivity, and cannot be reused after rotation. Logout revokes the
session, immediately invalidating its access tokens as well. Other devices keep
their own sessions. Requests from another Origin cannot mutate authentication.

Keep frontend and API on the same origin using the supplied Vite/nginx proxy.
For an HTTPS deployment, set `AUTH_COOKIE_SECURE=true`, use a strong private
`JWT_SECRET`, and configure your trusted reverse proxy to preserve the original
Host and scheme. Local HTTP development uses `AUTH_COOKIE_SECURE=false`.
This starter does not include email verification, password recovery, or an
internet-facing deployment configuration.


## Survey data and dashboard

The supplied `backend/data/ai_impact_on_students.csv` contains 50,000 records and
16 fields. It is included in the backend image, so no Kaggle download, account,
credentials, or manual seeding is needed. All signed-in users explore the same
survey snapshot; their account and session data remain separate.

Startup validates and imports the CSV in one transaction. Repeated starts do not
duplicate records. A changed, valid CSV replaces the survey snapshot; invalid
input or a failed write leaves the prior snapshot intact. The metadata table
records the source URL, original filename, row count, import time, column types,
and SHA-256. Original identifiers remain strings and missing measurements remain
null. See [the data contract](backend/data/README.md).

To validate and re-import the bundled file manually:

```sh
# From backend/, with DATABASE_URL set as in the local quick start:
uv run python -m app.survey data/ai_impact_on_students.csv
```

In Docker:

```sh
docker compose exec backend .venv/bin/python -m app.survey data/ai_impact_on_students.csv
```

To use an updated dataset, replace the bundled CSV and rebuild the backend, or
set `SURVEY_CSV_PATH` to a readable file for a local backend process. This path
selects the startup source on every restart; keep it consistent with manual
imports. For containers, mount the replacement file read-only and pass its
container path as `SURVEY_CSV_PATH`. This optional override is not needed for
the included data. A configured path that does not exist fails startup; when no
source is available and no path is explicitly configured, the UI shows an empty
state instead of fabricated results.

`GET /api/dashboard` requires the same Bearer access token as `/api/auth/me`.
Query parameters:

| Parameter | Purpose |
| --- | --- |
| `major`, `year`, `burnout` | Combine exact category filters; omit for all records |
| `group_by` | Category for GPA comparisons; defaults to `Major_Category` |
| `metric` | Numeric measurement for the histogram; defaults to `Weekly_GenAI_Hours` |
| `page` | 1-based page of 25 original records; resets on filter changes |

The response includes dataset provenance, filtered aggregates, grouped GPA means,
a 10-bin distribution, and a bounded page of rows. Each response uses one
consistent database snapshot, even while an import is replacing the dataset.
Unknown columns/filters and invalid pages return 422; missing or revoked sessions
return 401. Responses are not cached. SQL parameters bind all selected field
names and filter values. Filters and aggregation run on the server; the browser
never downloads all 50,000 rows.

Averages exclude missing values; GPA change is the mean of paired after-minus-
before values. Histogram counts exclude missing measurements and include the
maximum in the last bin. Constant measurements use one bin. The dashboard is
for exploratory analysis and does not imply that AI caused observed GPA changes.
