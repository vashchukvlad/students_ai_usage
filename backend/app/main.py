import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth import initialize_database, router


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
    yield


app = FastAPI(title="Student AI Usage API", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def protect_auth(request: Request, call_next):
    if request.url.path.startswith("/api/auth"):
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
