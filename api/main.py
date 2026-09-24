import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

import db

# get_config comes from auth, not config. It is the object the tests override,
# and importing load_config directly here would open a second path to the
# settings that no override could reach.
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

# Registration never reads a role from the request body. Hardcoding it here is
# the difference between an open signup form and privilege escalation.
NEW_USER_ROLE = "user"


def prepare_database(connection, config):
    """Create the tables, then seed the admin if one is configured.

    Takes a connection, not an engine, so an integration test can drive it on
    the rollback fixture and have the schema and the seeded row both undone.
    """
    db.apply_schema(connection)

    if not config.admin_username or not config.admin_password:
        print("no seed admin configured", file=sys.stderr)
        return

    # Lower-cased for the same reason login() lower-cases. Postgres stores
    # usernames case-sensitively, so a seeded "Admin" would exist and yet be
    # unreachable - which looks exactly like a wrong password, with nothing in
    # any log to say otherwise.
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
    # get_current_user raises 401 itself, so reaching this body means the
    # caller is known. The parameter only puts it in the dependency chain.
    user: AuthenticatedUser = Depends(get_current_user),
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
    # _engine() - it is a function, not an engine. And .begin(), not
    # .connect(): a write needs a transaction that commits, or the row
    # silently never lands.
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
    # Lower-cased to match the lookup in login(). If the two disagreed, an
    # account would be unreachable the moment it was created.
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
    # require_admin raises 403 itself, before this body runs - so a plain
    # user never reaches the deleter at all.
    user: AuthenticatedUser = Depends(require_admin),
):
    if deleter(alert_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such alert",
        )
