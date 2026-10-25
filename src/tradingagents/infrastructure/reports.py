"""Fixed report versions and append-only human review events in local SQLite."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.infrastructure.artifacts import digest, json_bytes, read_verified, utc_now
from tradingagents.infrastructure.evidence import verify_bundle


@contextmanager
def database(path: Path):
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def verify_run(path: Path, manifest_hash: str) -> dict:
    path = Path(path).resolve()
    manifest = json.loads(read_verified(path / "run.json", manifest_hash))
    if manifest["status"] != "completed":
        raise ValueError("run is not complete")
    for relative, ref in manifest["files"].items():
        target = (path / relative).resolve()
        if not target.is_relative_to(path):
            raise ValueError("artifact path escapes run")
        read_verified(target, ref)
    verify_bundle(path / "evidence", manifest["files"]["evidence/manifest.json"])
    return manifest


class ReportStore:
    """Trusted local storage API; network callers must use the scoped service."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with database(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, author TEXT NOT NULL,
                    run_path TEXT NOT NULL UNIQUE, manifest_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL, valid_until TEXT NOT NULL,
                    supersedes TEXT REFERENCES reports(id)
                );
                CREATE TABLE IF NOT EXISTS report_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL REFERENCES reports(id),
                    action TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL,
                    reason TEXT NOT NULL, acknowledgements TEXT NOT NULL,
                    previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS reports_no_update BEFORE UPDATE ON reports
                    BEGIN SELECT RAISE(ABORT, 'report versions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS reports_no_delete BEFORE DELETE ON reports
                    BEGIN SELECT RAISE(ABORT, 'report versions are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS report_events_no_update BEFORE UPDATE ON report_events
                    BEGIN SELECT RAISE(ABORT, 'review events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS report_events_no_delete BEFORE DELETE ON report_events
                    BEGIN SELECT RAISE(ABORT, 'review events are immutable'); END;
            """)

    def register(self, run_path: Path, manifest_hash: str, author: str, *, supersedes=None) -> str:
        run_path = Path(run_path)
        author = author.strip()
        manifest = verify_run(run_path, manifest_hash)
        inputs = json.loads((run_path / "input.json").read_bytes())
        # Quality is required for a reviewable version, not inferred from rating.
        if "quality.json" not in manifest["files"]:
            raise ValueError("quality checks are missing")
        report_id = uuid.uuid4().hex
        workspace = inputs["scope"]["workspace"]
        if not author.strip():
            raise ValueError("author is required")
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM reports WHERE run_path=?",
                             (str(run_path.resolve()),)).fetchone()
            if old:
                if (old["manifest_hash"], old["author"], old["supersedes"]) != (
                    manifest_hash, author, supersedes,
                ):
                    raise ValueError("run already registered with a different report contract")
                return old["id"]
            if supersedes:
                old = db.execute("SELECT workspace FROM reports WHERE id=?", (supersedes,)).fetchone()
                if not old or old["workspace"] != workspace:
                    raise ValueError("invalid superseded report")
            db.execute("INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)",
                       (report_id, workspace, author, str(run_path.resolve()), manifest_hash,
                        utc_now(), inputs["mandate"]["valid_until"], supersedes))
            self._append(db, report_id, "draft", author, "Run registered", [])
        return report_id

    @staticmethod
    def _append(db, report_id, action, actor, reason, acknowledgements):
        previous = db.execute(
            "SELECT event_hash FROM report_events WHERE report_id=? ORDER BY seq DESC LIMIT 1",
            (report_id,),
        ).fetchone()
        body = {"report_id": report_id, "action": action, "actor": actor, "at": utc_now(),
                "reason": reason, "acknowledgements": sorted(set(acknowledgements)),
                "previous_hash": previous["event_hash"] if previous else ""}
        event_hash = digest(json_bytes(body))
        db.execute("""INSERT INTO report_events
            (report_id,action,actor,at,reason,acknowledgements,previous_hash,event_hash)
            VALUES (?,?,?,?,?,?,?,?)""",
                   (report_id, action, actor, body["at"], reason,
                    json.dumps(body["acknowledgements"]), body["previous_hash"], event_hash))

    def get(self, report_id: str) -> dict:
        with database(self.path) as db:
            row = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise KeyError(report_id)
            result = dict(row)
            events = [dict(e) for e in db.execute(
                "SELECT * FROM report_events WHERE report_id=? ORDER BY seq", (report_id,))]
        previous = ""
        for event in events:
            body = {k: event[k] for k in ("report_id", "action", "actor", "at", "reason", "previous_hash")}
            body["acknowledgements"] = json.loads(event["acknowledgements"])
            if previous != body["previous_hash"] or digest(json_bytes(body)) != event["event_hash"]:
                raise ValueError("review audit integrity check failed")
            previous = event["event_hash"]
        result["events"] = events
        result["status"] = events[-1]["action"]
        result["expired"] = result["valid_until"] < datetime.now(UTC).date().isoformat()
        return result

    def transition(self, report_id: str, action: str, actor: str, reason: str, *,
                   acknowledgements=(), guard=None) -> dict:
        actor = actor.strip()
        if action not in {"approved", "rejected", "published", "withdrawn"}:
            raise ValueError("unsupported report transition")
        if not actor.strip() or not reason.strip():
            raise ValueError("actor and review reason are required")
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise KeyError(report_id)
            if guard is not None:
                guard(db)
            self.get(report_id)  # Validate the event chain before extending it.
            last = db.execute(
                "SELECT action FROM report_events WHERE report_id=? ORDER BY seq DESC LIMIT 1",
                (report_id,),
            ).fetchone()["action"]
            allowed = {"draft": {"approved", "rejected", "withdrawn"},
                       "approved": {"published", "withdrawn"}, "published": {"withdrawn"}}
            if action not in allowed.get(last, set()):
                raise ValueError(f"invalid transition from {last} to {action}")
            if action in {"approved", "rejected"} and actor == row["author"]:
                raise PermissionError("the author cannot review their own report")
            if action in {"approved", "published"}:
                if row["valid_until"] < datetime.now(UTC).date().isoformat():
                    raise ValueError("report is expired")
                path = Path(row["run_path"])
                verify_run(path, row["manifest_hash"])
                quality = json.loads((path / "quality.json").read_bytes())
                if quality["status"] == "blocked" or any(
                    item["severity"] == "block" for item in quality["issues"]
                ):
                    raise ValueError("hard quality rules block publication")
                required = {i["code"] for i in quality["issues"] if i["severity"] == "review"}
                if action == "approved" and not required <= set(acknowledgements):
                    raise ValueError("review must acknowledge every unresolved verification category")
            self._append(db, report_id, action, actor, reason, acknowledgements)
        return self.get(report_id)
