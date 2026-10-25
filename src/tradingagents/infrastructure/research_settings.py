"""Immutable per-template revisions, with compare-and-swap activation."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from tradingagents.domain.model_settings import SettingsConflict
from tradingagents.domain.research_settings import ResearchProfile
from tradingagents.infrastructure.artifacts import digest, json_bytes
from tradingagents.infrastructure.reports import database


class ResearchSettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        with database(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research_revisions (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, name TEXT NOT NULL,
                    version INTEGER NOT NULL, base_template TEXT NOT NULL, payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, actor TEXT NOT NULL, created REAL NOT NULL,
                    UNIQUE(workspace,name,version)
                );
                CREATE TABLE IF NOT EXISTS research_active (
                    workspace TEXT NOT NULL, name TEXT NOT NULL,
                    revision TEXT NOT NULL REFERENCES research_revisions(id),
                    PRIMARY KEY(workspace,name)
                );
                CREATE TRIGGER IF NOT EXISTS research_revision_no_update BEFORE UPDATE ON research_revisions
                    BEGIN SELECT RAISE(ABORT, 'research revisions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS research_revision_no_delete BEFORE DELETE ON research_revisions
                    BEGIN SELECT RAISE(ABORT, 'research revisions are immutable'); END;
            """)

    @staticmethod
    def decode(row):
        raw = json.loads(row["payload"])
        if digest(json_bytes(raw)) != row["payload_hash"]:
            raise ValueError("research revision integrity failed")
        return {"profile": ResearchProfile.model_validate(raw),
                **{key: row[key] for key in ("id", "version", "base_template", "created")}}

    def active(self, workspace):
        with database(self.path) as db:
            rows = db.execute("""SELECT r.* FROM research_active a
                JOIN research_revisions r ON r.id=a.revision WHERE a.workspace=?""",
                              (workspace,)).fetchall()
        return {row["name"]: self.decode(row) for row in rows}

    def save(self, workspace, data, actor, base_template):
        profile = data.profile
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT r.version,r.base_template FROM research_active a
                JOIN research_revisions r ON r.id=a.revision WHERE a.workspace=? AND a.name=?""",
                             (workspace, profile.name)).fetchone()
            if data.expected_version != (row["version"] if row else 0):
                raise SettingsConflict("research template changed; reload before saving")
            if row and base_template != row["base_template"]:
                raise ValueError("existing template baseline cannot change")
            revision, raw = uuid.uuid4().hex, json_bytes(profile.model_dump(mode="json"))
            db.execute("INSERT INTO research_revisions VALUES (?,?,?,?,?,?,?,?,?)",
                       (revision, workspace, profile.name, data.expected_version + 1, base_template,
                        raw.decode(), digest(raw), actor, time.time()))
            db.execute("INSERT OR REPLACE INTO research_active VALUES (?,?,?)",
                       (workspace, profile.name, revision))
        return {"name": profile.name, "version": data.expected_version + 1}
