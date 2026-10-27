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

The API initializes the `users` and `auth_sessions` tables at startup. No survey
data is required yet. Use a migration tool for future schema changes. The health
endpoint remains public for container readiness. Authentication integration tests
are skipped when `TEST_DATABASE_URL` is unset; the health tests still run.


## Authentication

The frontend supports account registration, sign-in, sign-out, session restoration
on reload, and automatic access-token refresh. The authenticated account page
uses the protected profile endpoint. Survey visualizations are still planned.

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
