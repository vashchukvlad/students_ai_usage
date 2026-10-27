import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import jwt
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/auth", tags=["authentication"])
passwords = PasswordHash.recommended()
# Equal-cost password verification when an account does not exist.
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))
bearer = HTTPBearer(auto_error=False)
ACCESS_SECONDS = 900
REFRESH_SECONDS = 60 * 60 * 24 * 7
COOKIE = "refresh_token"


class Credentials(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)


class Registration(Credentials):
    name: str = Field(min_length=1, max_length=80, pattern=r".*\S.*")


class User(BaseModel):
    id: str
    email: str
    name: str


class Tokens(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_SECONDS
    user: User


async def connect(request: Request):
    return await psycopg.AsyncConnection.connect(
        request.app.state.database_url, row_factory=dict_row, connect_timeout=3
    )


async def initialize_database(database_url: str):
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                refresh_hash TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """)


def refresh_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def issue_tokens(
    request: Request, response: Response, user: dict, session_id: str, refresh: str
) -> Tokens:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user["id"]),
            "sid": session_id,
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(seconds=ACCESS_SECONDS),
            "iss": "students-ai-usage",
            "aud": "students-ai-usage-api",
        },
        request.app.state.jwt_secret,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE,
        refresh,
        max_age=REFRESH_SECONDS,
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )
    response.headers["Cache-Control"] = "no-store"
    return Tokens(access_token=token, user=User(**{**user, "id": str(user["id"])}))


async def create_session(request: Request, response: Response, user: dict) -> Tokens:
    refresh = secrets.token_urlsafe(48)
    session_id = str(uuid4())
    async with await connect(request) as connection:
        await connection.execute(
            "INSERT INTO auth_sessions (id, user_id, refresh_hash, expires_at) "
            "VALUES (%s, %s, %s, %s)",
            (
                session_id,
                user["id"],
                refresh_hash(refresh),
                datetime.now(UTC) + timedelta(seconds=REFRESH_SECONDS),
            ),
        )
    return issue_tokens(request, response, user, session_id, refresh)


@router.post("/register", response_model=Tokens, status_code=201)
async def register(data: Registration, request: Request, response: Response):
    user = {
        "id": str(uuid4()),
        "email": str(data.email).lower(),
        "name": data.name.strip(),
    }
    hashed = await run_in_threadpool(passwords.hash, data.password)
    try:
        async with await connect(request) as connection:
            await connection.execute(
                "INSERT INTO users (id, email, name, password_hash) VALUES (%s,%s,%s,%s)",
                (user["id"], user["email"], user["name"], hashed),
            )
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(409, "An account with this email already exists") from error
    return await create_session(request, response, user)


@router.post("/login", response_model=Tokens)
async def login(data: Credentials, request: Request, response: Response):
    async with await connect(request) as connection:
        cursor = await connection.execute(
            "SELECT * FROM users WHERE email = %s", (str(data.email).lower(),)
        )
        user = await cursor.fetchone()
    valid = await run_in_threadpool(
        passwords.verify, data.password, user["password_hash"] if user else DUMMY_HASH
    )
    if not user or not valid:
        raise HTTPException(401, "Invalid email or password")
    return await create_session(request, response, user)


@router.post("/refresh", response_model=Tokens)
async def refresh(request: Request, response: Response):
    old_refresh = request.cookies.get(COOKIE)
    if not old_refresh:
        raise HTTPException(401, "Please sign in again")
    new_refresh = secrets.token_urlsafe(48)
    async with await connect(request) as connection:
        # Atomic compare-and-swap prevents concurrent reuse of a refresh token.
        cursor = await connection.execute(
            "UPDATE auth_sessions SET refresh_hash = %s, expires_at = %s "
            "WHERE refresh_hash = %s AND expires_at > now() RETURNING id, user_id",
            (
                refresh_hash(new_refresh),
                datetime.now(UTC) + timedelta(seconds=REFRESH_SECONDS),
                refresh_hash(old_refresh),
            ),
        )
        session = await cursor.fetchone()
        if not session:
            raise HTTPException(401, "Session expired; please sign in again")
        cursor = await connection.execute(
            "SELECT id, email, name FROM users WHERE id = %s", (session["user_id"],)
        )
        user = await cursor.fetchone()
    return issue_tokens(request, response, user, str(session["id"]), new_refresh)


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    unauthorized = HTTPException(
        401, "Please sign in again", headers={"WWW-Authenticate": "Bearer"}
    )
    if not credentials:
        raise unauthorized
    try:
        claims = jwt.decode(
            credentials.credentials,
            request.app.state.jwt_secret,
            algorithms=["HS256"],
            issuer="students-ai-usage",
            audience="students-ai-usage-api",
            options={"require": ["exp", "iat", "sub", "sid", "type"]},
        )
        if claims["type"] != "access":
            raise unauthorized
        # IDs are bound to a live session: logout invalidates access tokens too.
        async with await connect(request) as connection:
            cursor = await connection.execute(
                "SELECT users.id, users.email, users.name FROM users "
                "JOIN auth_sessions ON users.id = auth_sessions.user_id "
                "WHERE auth_sessions.id::text = %s AND users.id::text = %s "
                "AND auth_sessions.expires_at > now()",
                (claims["sid"], claims["sub"]),
            )
            user = await cursor.fetchone()
        if not user:
            raise unauthorized
        return User(**{**user, "id": str(user["id"])})
    except jwt.InvalidTokenError as error:
        raise unauthorized from error


@router.get("/me", response_model=User)
async def me(user: Annotated[User, Depends(current_user)]):
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        async with await connect(request) as connection:
            await connection.execute(
                "DELETE FROM auth_sessions WHERE refresh_hash = %s",
                (refresh_hash(token),),
            )
    response.delete_cookie(
        COOKIE,
        path="/api/auth",
        secure=request.app.state.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
