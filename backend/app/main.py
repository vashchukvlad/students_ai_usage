import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set; see README.md")
    app.state.database_url = database_url
    yield


app = FastAPI(title="Student AI Usage API", lifespan=lifespan)


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
