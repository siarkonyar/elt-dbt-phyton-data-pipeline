import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

import db
from auth import (
    ADMIN_ROLE,
    AuthenticatedUser,
    get_config,
    get_current_user,
    require_admin,
)
from config import ConfigError
from passwords import hash_password, verify_password
from serialize import candle_to_dict
from tokens import create_token

NEW_USER_ROLE = "user"


def prepare_database(connection, config):
    db.apply_schema(connection)

    if not config.admin_username or not config.admin_password:
        print("no seed admin configured", file=sys.stderr)
        return

    db.create_user(
        connection,
        username=config.admin_username.strip().lower(),
        password_hash=hash_password(config.admin_password),
        role=ADMIN_ROLE,
    )


@asynccontextmanager
async def lifespan(app):
    """Runs once per container, before the first request is served.

    The two failure modes get opposite treatment on purpose.

    ConfigError is re-raised. The container dies, compose restarts it, and the
    log says JWT_SECRET is not set. A visible crash loop is the right answer to
    a missing secret; a server that boots happily without one is worse.

    SQLAlchemyError is swallowed. Postgres blinking during boot must not take
    the process down - /health stays green and the next login reports the real
    problem, rather than the whole service disappearing over a slow database.
    """
    try:
        with _engine().begin() as connection:
            prepare_database(connection, get_config())
    except ConfigError:
        print("the api cannot start without its settings", file=sys.stderr)
        raise
    except SQLAlchemyError as error:
        print(f"could not prepare the database at startup: {error}", file=sys.stderr)

    yield


app = FastAPI(title="ELT candles API", lifespan=lifespan)

@app.get("/health")
def health():
  return {"status": "ok"}

@lru_cache(maxsize=1)
def _engine():
  return db.get_engine()

def read_candles(symbol, hours):
  return db.read_candles(_engine(), symbol, hours)

def get_reader():
  return read_candles

@app.get("/candles")
def candles(
    symbol: str = Query(..., min_length=1, max_length=10),
    hours: int = Query(1, ge=1, le=24),
    reader=Depends(get_reader),
    user: AuthenticatedUser=Depends(get_current_user)#this already raises an error if the user is not authenticated
):
    return [candle_to_dict(row) for row in reader(symbol.upper(), hours)]


def read_user(username):
    with _engine().connect() as connection:
        return db.read_user(connection, username)

def get_user_reader():
    return read_user

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)

class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)

@app.post("/auth/login")
def login(
    credentials: LoginRequest,
    reader=Depends(get_user_reader),
    config=Depends(get_config),
):
    username = credentials.username.strip().lower()
    user = reader(username)

    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="wrong username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_token(
        config.jwt_secret,
        username,
        user.role,
        datetime.now(UTC),
        config.token_expiry_seconds,
    )

    return {"access_token": token, "token_type": "bearer", "role": user.role}

def create_user(username, hashed_password, role=NEW_USER_ROLE):
    with _engine().begin() as connection:
        return db.create_user(
            connection,
            username=username,
            password_hash=hashed_password,
            role=role,
        )

def get_user_creator():
    return create_user

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    credentials: RegisterRequest,
    user_creator=Depends(get_user_creator),
):
    username = credentials.username.strip().lower()
    password = credentials.password

    hashed_password = hash_password(password=password)

    user_id = user_creator(username, hashed_password, NEW_USER_ROLE)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that username is already taken",
        )

    return {"username": username, "role": NEW_USER_ROLE}


def delete_alert(alert_id):
    with _engine().begin() as connection:
        return db.delete_alert(connection, alert_id)

def get_alert_deleter():
    return delete_alert

@app.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_alert(
    alert_id: int,
    deleter=Depends(get_alert_deleter),
    user: AuthenticatedUser = Depends(require_admin),#this already raises an error if the user is not authenticated
):
    if deleter(alert_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such alert",
        )
