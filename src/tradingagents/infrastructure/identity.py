"""Revocable scoped local bearer identities; production OIDC is a separate adapter."""

from __future__ import annotations

import json
import secrets
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from tradingagents.infrastructure.artifacts import component, digest, json_bytes
from tradingagents.infrastructure.reports import database

SCOPES = frozenset({
    "task:create", "task:read", "task:cancel", "report:read", "report:register",
    "report:review", "report:publish", "report:withdraw", "ops:read", "ops:control",
    "cost:reconcile", "audit:read", "evaluation:write", "evaluation:read",
})
AUDIT_REQUEST: ContextVar[str | None] = ContextVar("research_request_id", default=None)


class AuthenticationError(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace: str
    scopes: frozenset[str]

    def require(self, workspace: str, scope: str):
        if workspace != self.workspace or scope not in self.scopes:
            raise PermissionError("workspace or scope is not authorized")


class IdentityStore:
    def __init__(self, path: Path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with database(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS identities (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL, workspace TEXT NOT NULL, scopes TEXT NOT NULL,
                    expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS access_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
                    subject TEXT NOT NULL, workspace TEXT NOT NULL, action TEXT NOT NULL,
                    object_id TEXT NOT NULL, outcome TEXT NOT NULL, at REAL NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS access_no_update BEFORE UPDATE ON access_events
                    BEGIN SELECT RAISE(ABORT, 'access audit is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS access_no_delete BEFORE DELETE ON access_events
                    BEGIN SELECT RAISE(ABORT, 'access audit is immutable'); END;
            """)

    def issue(self, subject: str, workspace: str, scopes, *, ttl_seconds=3600) -> tuple[str, str]:
        """Local operator only. No remote endpoint can issue or expand scopes."""
        subject = component(subject.strip().lower())
        workspace = component(workspace)
        scopes = frozenset(scopes)
        if not scopes or not scopes <= SCOPES or not 1 <= ttl_seconds <= 86400:
            raise ValueError("known scopes and lifetime of at most one day are required")
        token, identity_id = secrets.token_urlsafe(32), uuid.uuid4().hex
        with database(self.path) as db:
            db.execute("INSERT INTO identities VALUES (?,?,?,?,?,?,0)",
                       (identity_id, digest(token.encode()), subject, workspace,
                        json_bytes(sorted(scopes)).decode(), self.clock() + ttl_seconds))
        self.audit(Principal(subject, workspace, scopes), "identity:issued", identity_id)
        return identity_id, token

    def authenticate(self, token: str) -> Principal:
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise AuthenticationError("invalid or expired bearer credential")
        with database(self.path) as db:
            row = db.execute("SELECT * FROM identities WHERE token_hash=?",
                             (digest(token.encode()),)).fetchone()
        if row is None or row["revoked"] or row["expires"] <= self.clock():
            raise AuthenticationError("invalid or expired bearer credential")
        return Principal(row["subject"], row["workspace"], frozenset(json.loads(row["scopes"])))

    def revoke(self, identity_id: str):
        with database(self.path) as db:
            row = db.execute("SELECT * FROM identities WHERE id=?", (identity_id,)).fetchone()
            if row is None:
                raise KeyError(identity_id)
            db.execute("UPDATE identities SET revoked=1 WHERE id=?", (identity_id,))
        self.audit(Principal("local-operator", row["workspace"], frozenset()),
                   "identity:revoked", identity_id)

    def audit(self, principal: Principal, action: str, object_id: str = "", *,
              outcome="success", request_id: str | None = None):
        with database(self.path) as db:
            db.execute("""INSERT INTO access_events
                (request_id,subject,workspace,action,object_id,outcome,at) VALUES (?,?,?,?,?,?,?)""",
                       (request_id or AUDIT_REQUEST.get() or uuid.uuid4().hex,
                        principal.subject, principal.workspace,
                        action[:100], object_id[:128], outcome, self.clock()))
