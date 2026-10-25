"""Local password accounts and revocable HttpOnly browser sessions."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from tradingagents.infrastructure.artifacts import digest
from tradingagents.infrastructure.identity import SCOPES, AuthenticationError, Principal
from tradingagents.infrastructure.reports import database

ROLE_SCOPES = {
    "admin": SCOPES,
    "researcher": frozenset({
        "task:create", "task:read", "task:cancel", "task:execute", "report:read",
        "report:register", "evaluation:read", "evaluation:write", "settings:read",
    }),
    "reviewer": frozenset({
        "task:read", "report:read", "report:review", "report:publish", "report:withdraw",
        "evaluation:read", "settings:read",
    }),
    "operator": frozenset({
        "task:read", "report:read", "evaluation:read", "ops:read", "ops:control",
        "cost:reconcile", "audit:read", "settings:read",
    }),
}
SESSION_SECONDS = 7 * 86400


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr

    @field_validator("username")
    @classmethod
    def username_valid(cls, value):
        value = value.strip().lower()
        if not value or any(not (c.isascii() and (c.isalnum() or c in "_-.")) for c in value):
            raise ValueError("username must use letters, digits, dots, underscores or hyphens")
        return value

    @field_validator("password")
    @classmethod
    def password_bounded(cls, value):
        if not 1 <= len(value.get_secret_value()) <= 256:
            raise ValueError("password length is invalid")
        return value


class AccountInput(LoginInput):
    role: str = "researcher"

    @field_validator("role")
    @classmethod
    def role_known(cls, value):
        if value not in ROLE_SCOPES:
            raise ValueError("unknown account role")
        return value

    @field_validator("password")
    @classmethod
    def password_new(cls, value):
        if len(value.get_secret_value()) < 8:
            raise ValueError("new password requires at least 8 characters")
        return value


class LoginThrottled(ValueError):
    pass


def _password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                          n=16384, r=8, p=1, dklen=32).hex()


class BrowserAccounts:
    def __init__(self, path: Path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        with database(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS browser_accounts (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    workspace TEXT NOT NULL, role TEXT NOT NULL, salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL
                    REFERENCES browser_accounts(id), csrf TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_login_failures (
                    username_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL, until REAL NOT NULL
                );
            """)

    def setup_required(self):
        with database(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM browser_accounts").fetchone()[0] == 0

    def create(self, workspace: str, data: AccountInput, *, first=False):
        data = AccountInput.model_validate(data)
        account_id, salt = uuid.uuid4().hex, secrets.token_hex(16)
        password_hash = _password_hash(data.password.get_secret_value(), salt)
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if first and db.execute("SELECT 1 FROM browser_accounts LIMIT 1").fetchone():
                raise ValueError("workspace account has already been initialized")
            if db.execute("SELECT 1 FROM browser_accounts WHERE username=?", (data.username,)).fetchone():
                raise ValueError("account name already exists")
            role = "admin" if first else data.role
            db.execute("INSERT INTO browser_accounts VALUES (?,?,?,?,?,?,?)",
                       (account_id, data.username, workspace, role, salt, password_hash, self.clock()))
        return {"id": account_id, "username": data.username, "role": role}

    def login(self, data: LoginInput):
        data = LoginInput.model_validate(data)
        username_hash = digest(data.username.encode())
        with database(self.path) as db:
            failed = db.execute("SELECT * FROM browser_login_failures WHERE username_hash=?",
                                (username_hash,)).fetchone()
            if failed and failed["until"] > self.clock() and failed["failures"] >= 5:
                raise LoginThrottled("too many login attempts")
            account = db.execute("SELECT * FROM browser_accounts WHERE username=?",
                                 (data.username,)).fetchone()
        # Unknown accounts perform the same password work; never return account existence.
        salt = account["salt"] if account else "00" * 16
        actual = _password_hash(data.password.get_secret_value(), salt)
        if account is None or not hmac.compare_digest(actual, account["password_hash"]):
            with database(self.path) as db:
                db.execute("""INSERT INTO browser_login_failures VALUES (?,1,?)
                    ON CONFLICT(username_hash) DO UPDATE SET
                    failures=CASE WHEN until <= ? THEN 1 ELSE failures+1 END, until=?""",
                           (username_hash, self.clock() + 60, self.clock(), self.clock() + 60))
            raise AuthenticationError("username or password is incorrect")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with database(self.path) as db:
            db.execute("DELETE FROM browser_login_failures WHERE username_hash=?", (username_hash,))
            db.execute("DELETE FROM browser_sessions WHERE expires<=?", (self.clock(),))
            db.execute("INSERT INTO browser_sessions VALUES (?,?,?,?)",
                       (digest(token.encode()), account["id"], csrf, self.clock() + SESSION_SECONDS))
        return token

    def authenticate(self, token: str):
        if not 32 <= len(token) <= 128:
            raise AuthenticationError("login is required")
        with database(self.path) as db:
            row = db.execute("""SELECT a.*,s.csrf,s.expires FROM browser_sessions s
                JOIN browser_accounts a ON a.id=s.account_id WHERE s.token_hash=?""",
                             (digest(token.encode()),)).fetchone()
        if not row or row["expires"] <= self.clock():
            raise AuthenticationError("browser session has expired")
        # Account ids are server-generated; a username cannot impersonate an old report author.
        principal = Principal("user-" + row["id"], row["workspace"], ROLE_SCOPES[row["role"]])
        return principal, {"username": row["username"], "role": row["role"], "csrf": row["csrf"]}

    def logout(self, token: str):
        with database(self.path) as db:
            db.execute("DELETE FROM browser_sessions WHERE token_hash=?", (digest(token.encode()),))

    def list(self, workspace):
        with database(self.path) as db:
            return [dict(row) for row in db.execute(
                "SELECT id,username,role,created FROM browser_accounts WHERE workspace=? "
                "ORDER BY created,id", (workspace,),
            )]
