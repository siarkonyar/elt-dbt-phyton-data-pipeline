from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

import db

# get_config comes from auth, not config. It is the object the tests override,
# and importing load_config directly here would open a second path to the
# settings that no override could reach.
from auth import AuthenticatedUser, get_config, get_current_user, require_admin
from passwords import hash_password, verify_password
from serialize import candle_to_dict
from tokens import create_token

# Registration never reads a role from the request body. Hardcoding it here is
# the difference between an open signup form and privilege escalation.
NEW_USER_ROLE = "user"

app = FastAPI(title="ELT candles API")

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
    user: AuthenticatedUser = Depends(get_current_user),
):
    # No check on `user` here on purpose. get_current_user either returns an
    # AuthenticatedUser or raises 401 itself, and FastAPI resolves it before
    # this body runs - so by the time we are here, the caller is known. The
    # parameter exists only to put that dependency in the chain. Reading is
    # not an admin power, so any role is fine.
    return [candle_to_dict(row) for row in reader(symbol.upper(), hours)]


def read_user(username):
    # .connect() for a read. The two writers below use .begin(), which commits.
    with _engine().connect() as connection:
        return db.read_user(connection, username)

def get_user_reader():
    return read_user

def create_user(username, password_hash, role):
    with _engine().begin() as connection:
        return db.create_user(connection, username, password_hash, role)

def get_user_creator():
    return create_user

def delete_alert(alert_id):
    with _engine().begin() as connection:
        return db.delete_alert(connection, alert_id)

def get_alert_deleter():
    return delete_alert

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

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    credentials: RegisterRequest,
    creator=Depends(get_user_creator),
):
    """Open signup, and it can only ever make a plain user.

    No config and no token here - registering does not log you in. The caller
    gets a 201 and then posts to /auth/login like anyone else.
    """
    # Lower-cased before it is stored, matching the lookup in login(). If the
    # two ever disagreed, an account would be unreachable the moment it was made.
    username = credentials.username.strip().lower()

    # NEW_USER_ROLE, never credentials.role. RegisterRequest has no role field,
    # so Pydantic drops one if a caller sends it - but the hardcoded argument is
    # what actually makes that safe rather than incidental.
    user_id = creator(username, hash_password(credentials.password), NEW_USER_ROLE)

    # None means ON CONFLICT DO NOTHING found an existing row. See
    # db.create_user - one statement answers both "created" and "taken".
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that username is already taken",
        )

    return {"username": username, "role": NEW_USER_ROLE}

@app.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_alert(
    alert_id: int,
    deleter=Depends(get_alert_deleter),
    user: AuthenticatedUser = Depends(require_admin),
):
    """The one admin-only route.

    require_admin is resolved before this body runs, so a plain user never
    reaches the deleter at all - the 403 happens before any work is done.

    Named remove_alert rather than delete_alert because the module-level seam
    above already owns that name, the same way `candles` sits beside
    `read_candles`.
    """
    # 0 rows means no such alert. db.delete_alert returns the count precisely so
    # that mapping lives here, in the layer that knows about status codes.
    if deleter(alert_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such alert",
        )

