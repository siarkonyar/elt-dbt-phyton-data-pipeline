import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, StringConstraints
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
from emails import EMAIL_PATTERN, MAX_EMAIL_LENGTH
from passwords import hash_password, verify_password
from serialize import alert_to_dict, candle_to_dict
from tokens import create_token

NEW_USER_ROLE = "user"


def prepare_database(connection, config):
    db.apply_schema(connection)

    if not config.admin_email or not config.admin_password:
        print("no seed admin configured", file=sys.stderr)
        return

    db.create_user(
        connection,
        email=config.admin_email.strip().lower(),
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
    #this already raises an error if the user is not authenticated
    user: AuthenticatedUser=Depends(get_current_user)
):
    return [candle_to_dict(row) for row in reader(symbol.upper(), hours)]


def read_user(email):
    with _engine().connect() as connection:
        return db.read_user(connection, email)

def get_user_reader():
    return read_user

# Trimmed and lower-cased before the pattern runs, so " Ada@Example.com " is
# accepted and stored as "ada@example.com". Postgres compares case-sensitively,
# so without the lower-casing one person could hold two accounts.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=MAX_EMAIL_LENGTH,
        pattern=EMAIL_PATTERN,
    ),
]

class LoginRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=72)

class RegisterRequest(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=72)

@app.post("/auth/login")
def login(
    credentials: LoginRequest,
    reader=Depends(get_user_reader),
    config=Depends(get_config),
):
    email = credentials.email
    user = reader(email)

    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="wrong email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_token(
        config.jwt_secret,
        email,
        user.role,
        datetime.now(UTC),
        config.token_expiry_seconds,
    )

    return {"access_token": token, "token_type": "bearer", "role": user.role}

def create_user(email, hashed_password, role=NEW_USER_ROLE):
    with _engine().begin() as connection:
        return db.create_user(
            connection,
            email=email,
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
    email = credentials.email
    password = credentials.password

    hashed_password = hash_password(password=password)

    user_id = user_creator(email, hashed_password, NEW_USER_ROLE)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with that email already exists",
        )

    return {"email": email, "role": NEW_USER_ROLE}


AlertSymbol = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_upper=True, min_length=1, max_length=10
    ),
]

class AlertRequest(BaseModel):
    symbol: AlertSymbol
    direction: Literal["above", "below"]
    threshold: float = Field(gt=0)

def create_alert(email, symbol, direction, threshold):
    with _engine().begin() as connection:
        return db.create_alert(
            connection,
            email=email,
            symbol=symbol,
            direction=direction,
            threshold=threshold,
        )

def get_alert_creator():
    return create_alert

@app.post("/alerts", status_code=status.HTTP_201_CREATED)
def add_alert(
    alert: AlertRequest,
    creator=Depends(get_alert_creator),
    user: AuthenticatedUser = Depends(get_current_user),
):
    alert_id = creator(user.email, alert.symbol, alert.direction, alert.threshold)

    # The token is valid but its account is gone - deleted after it was issued.
    if alert_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="this account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "alert_id": alert_id,
        "symbol": alert.symbol,
        "direction": alert.direction,
        "threshold": alert.threshold,
    }

def read_alerts(email):
    with _engine().connect() as connection:
        return db.read_alerts(connection, email)

def get_alert_reader():
    return read_alerts

@app.get("/alerts")
def list_alerts(
    reader=Depends(get_alert_reader),
    user: AuthenticatedUser = Depends(get_current_user),
):
    # None tells read_alerts not to filter by owner.
    email = None if user.role == ADMIN_ROLE else user.email
    return [alert_to_dict(row) for row in reader(email)]
    #REVIEW: ask if this is safe or not


def delete_alert(alert_id):
    with _engine().begin() as connection:
        return db.delete_alert(connection, alert_id)

def get_alert_deleter():
    return delete_alert

@app.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_alert(
    alert_id: int,
    deleter=Depends(get_alert_deleter),
    #this already raises an error if the user is not authenticated
    user: AuthenticatedUser = Depends(require_admin),
):
    if deleter(alert_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such alert",
        )
