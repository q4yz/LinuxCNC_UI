"""``/api/v1/auth`` and ``/api/v1/users`` — accounts and logins (#131).

* Anyone without a login is a viewer (``core.auth.current_user``).
* ``POST /auth/setup`` creates the first account (an admin) — only while
  none exists; until then every caller is the local admin, as before.
* ``POST /auth/login`` trades a user name and password for a session
  token (``core.session_token``) that does not expire; it ends with a
  password change, ``POST /auth/logout-everywhere`` or the account's
  deletion.
* ``/users`` — admins add, change and delete accounts.
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, Field

from core.auth import current_user
from core.permissions import Permission, level
from core.session_token import issue
from core.users_db import ACCOUNT_ROLES, Account, UserError, get_user_store

router = APIRouter(tags=["auth"])

_NAME = Path(..., description="The account's user name.")

#: Failed logins per name before the name waits (s) — guessing passwords
#: over the network gets slow.
MAX_FAILURES = 5
LOCKOUT_S = 30.0


class _Failures:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, tuple[int, float]] = {}

    def locked_for(self, name: str, now: float) -> float:
        with self._lock:
            count, last = self._by_name.get(name.lower(), (0, 0.0))
            return max(0.0, last + LOCKOUT_S - now) if count >= MAX_FAILURES else 0.0

    def failed(self, name: str, now: float) -> None:
        with self._lock:
            count, _ = self._by_name.get(name.lower(), (0, 0.0))
            self._by_name[name.lower()] = (count + 1, now)

    def succeeded(self, name: str) -> None:
        with self._lock:
            self._by_name.pop(name.lower(), None)


_failures = _Failures()


class CurrentUserResponse(BaseModel):
    name: str
    role: str = Field(..., description="admin, user, viewer or agent.")
    authenticated: bool = Field(..., description="Logged in with an account.")
    accounts_exist: bool = Field(..., description="False: no account yet, every caller is the local admin.")
    permissions: dict[str, str] = Field(..., description="Permission -> allow / confirm / deny for this role.")


class Credentials(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str = Field(..., description="Session token: 'Authorization: Bearer <token>' (or X-Api-Key).")
    user: CurrentUserResponse


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class UserResponse(BaseModel):
    name: str
    role: str


class UserListResponse(BaseModel):
    users: list[UserResponse]
    roles: list[str] = Field(..., description="The roles an account can have.")


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserUpdate(BaseModel):
    role: str | None = None
    password: str | None = Field(None, description="A new password (ends the user's sessions).")


def _me(name: str, role: str, authenticated: bool, accounts_exist: bool) -> CurrentUserResponse:
    return CurrentUserResponse(
        name=name, role=role, authenticated=authenticated, accounts_exist=accounts_exist,
        permissions={p.value: level(role, p).value for p in Permission},
    )


def _account_me(account: Account) -> CurrentUserResponse:
    return _me(account.name, account.role, True, True)


def _bad(exc: UserError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _require_account(request: Request) -> Account:
    user = current_user(request)
    account = get_user_store().get(user.name) if user.name not in ("local", "guest", "agent") else None
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Log in first")
    return account


@router.get("/api/v1/auth/me", response_model=CurrentUserResponse, operation_id="authMe",
            summary="Who is calling")
def me(request: Request) -> CurrentUserResponse:
    user = current_user(request)
    store = get_user_store()
    authenticated = user.name not in ("local", "guest", "agent") and store.get(user.name) is not None
    return _me(user.name, user.role, authenticated, store.has_accounts())


@router.post("/api/v1/auth/login", response_model=LoginResponse, operation_id="authLogin",
             summary="Log in", responses={401: {"description": "Wrong user name or password."},
                                          429: {"description": "Too many failed attempts: wait."}})
def login(body: Credentials) -> LoginResponse:
    now = time.time()
    wait = _failures.locked_for(body.username, now)
    if wait > 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many failed logins: try again in {wait:.0f} s")
    account = get_user_store().authenticate(body.username, body.password)
    if account is None:
        _failures.failed(body.username, now)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong user name or password")
    _failures.succeeded(body.username)
    return LoginResponse(token=issue(account), user=_account_me(account))


@router.post("/api/v1/auth/setup", response_model=LoginResponse, operation_id="authSetup",
             summary="Create the first account (an admin)",
             responses={400: {"description": "An account exists already, or the name / password is invalid."}})
def setup(body: Credentials) -> LoginResponse:
    try:
        account = get_user_store().create_first_admin(body.username, body.password)
    except UserError as exc:
        raise _bad(exc) from None
    return LoginResponse(token=issue(account), user=_account_me(account))


@router.put("/api/v1/auth/password", response_model=LoginResponse, operation_id="authChangePassword",
            summary="Change your own password (other sessions end)")
def change_password(body: PasswordChange, request: Request) -> LoginResponse:
    account = _require_account(request)
    store = get_user_store()
    if store.authenticate(account.name, body.current_password) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is wrong")
    try:
        store.set_password(account.name, body.new_password)
    except UserError as exc:
        raise _bad(exc) from None
    fresh = store.get(account.name)
    assert fresh is not None
    return LoginResponse(token=issue(fresh), user=_account_me(fresh))


@router.post("/api/v1/auth/logout-everywhere", status_code=204, operation_id="authLogoutEverywhere",
             summary="End every session of your account")
def logout_everywhere(request: Request) -> Response:
    get_user_store().revoke_sessions(_require_account(request).name)
    return Response(status_code=204)


@router.get("/api/v1/users", response_model=UserListResponse, operation_id="listUsers", summary="List accounts")
def list_users() -> UserListResponse:
    return UserListResponse(users=[UserResponse(name=a.name, role=a.role) for a in get_user_store().list()],
                            roles=list(ACCOUNT_ROLES))


@router.post("/api/v1/users", response_model=UserResponse, status_code=201, operation_id="createUser",
             summary="Add an account")
def create_user(body: UserCreate) -> UserResponse:
    try:
        account = get_user_store().create(body.username, body.password, body.role)
    except UserError as exc:
        raise _bad(exc) from None
    return UserResponse(name=account.name, role=account.role)


@router.put("/api/v1/users/{name}", response_model=UserResponse, operation_id="updateUser",
            summary="Change an account's role or password")
def update_user(body: UserUpdate, name: str = _NAME) -> UserResponse:
    store = get_user_store()
    try:
        if body.role is not None:
            store.set_role(name, body.role)
        if body.password:
            store.set_password(name, body.password)
    except UserError as exc:
        raise _bad(exc) from None
    account = store.get(name)
    assert account is not None
    return UserResponse(name=account.name, role=account.role)


@router.delete("/api/v1/users/{name}", status_code=204, operation_id="deleteUser", summary="Delete an account")
def delete_user(name: str = _NAME) -> Response:
    try:
        get_user_store().delete(name)
    except UserError as exc:
        raise _bad(exc) from None
    return Response(status_code=204)
