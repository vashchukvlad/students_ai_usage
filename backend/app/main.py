import os
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth import initialize_database, router
from app.survey import DEFAULT_CSV, import_csv, initialize_survey
from app.survey import router as survey_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set; see README.md")
    app.state.database_url = database_url
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    app.state.jwt_secret = secret
    app.state.cookie_secure = (
        os.environ.get("AUTH_COOKIE_SECURE", "false").lower() == "true"
    )
    await initialize_database(database_url)
    await initialize_survey(database_url)
    csv_path = Path(os.environ.get("SURVEY_CSV_PATH", str(DEFAULT_CSV)))
    if csv_path.is_file():
        await import_csv(database_url, csv_path)
    elif "SURVEY_CSV_PATH" in os.environ:
        raise RuntimeError(f"SURVEY_CSV_PATH does not exist: {csv_path}")
    yield


app = FastAPI(title="Student AI Usage API", lifespan=lifespan)
app.include_router(router)
app.include_router(survey_router)


@app.middleware("http")
async def protect_auth(request: Request, call_next):
    if request.url.path.startswith("/api/auth") or request.url.path == "/api/dashboard":
        origin = request.headers.get("origin")
        if (
            request.method == "POST"
            and origin
            and origin != str(request.base_url).rstrip("/")
        ):
            return JSONResponse(
                {"detail": "Cross-origin authentication is not allowed"},
                status_code=403,
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    return await call_next(request)


@app.exception_handler(psycopg.Error)
async def database_error(request: Request, error: psycopg.Error):
    return JSONResponse(
        {"detail": "Database unavailable. Please try again."},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
async def health():
    try:
        async with (
            await psycopg.AsyncConnection.connect(
                app.state.database_url, connect_timeout=3
            ) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute("SELECT 1")
            await cursor.fetchone()
    except psycopg.Error as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    return {"status": "ok", "database": "ok"}
