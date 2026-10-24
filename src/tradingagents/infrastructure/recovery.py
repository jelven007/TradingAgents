"""Consistent SQLite backups plus pinned artifacts, restored into a fresh directory."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from tradingagents.infrastructure.artifacts import (
    digest,
    json_bytes,
    read_verified,
    utc_now,
    write_json_once,
    write_once,
)
from tradingagents.infrastructure.evaluations import EvaluationStore
from tradingagents.infrastructure.evidence import verify_bundle
from tradingagents.infrastructure.reports import ReportStore, database, verify_run
from tradingagents.infrastructure.tasks import TaskStore


def _safe(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("backup reference escapes storage")
    return target


def validate_database(path: Path):
    with database(path) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("database reference integrity failed")
        tasks = [r["id"] for r in db.execute("SELECT id FROM tasks")]
        reports = [r["id"] for r in db.execute("SELECT id FROM reports")]
    store = TaskStore(path)
    for task in tasks:
        store.get(task)
    report_store = ReportStore(path)
    for report in reports:
        report_store.get(report)
    EvaluationStore(path).validate()


def backup(db_path: Path, artifact_root: Path, destination: Path) -> str:
    artifact_root, destination = Path(artifact_root).resolve(), Path(destination).resolve()
    if destination.is_relative_to(artifact_root):
        raise ValueError("backup must be outside the artifact root")
    destination.mkdir(parents=True, exist_ok=False)
    destination.chmod(0o700)
    snapshot = destination / "store.sqlite"
    with sqlite3.connect(db_path) as source, sqlite3.connect(snapshot) as target:
        source.backup(target)
    validate_database(snapshot)
    with database(snapshot) as db:
        refs = {r["result_path"]: r["manifest_hash"] for r in db.execute(
            "SELECT result_path,manifest_hash FROM tasks WHERE status='succeeded'")}
        for row in db.execute("SELECT run_path,manifest_hash FROM reports"):
            if row["run_path"] in refs and refs[row["run_path"]] != row["manifest_hash"]:
                raise ValueError("task/report manifest disagreement")
            refs[row["run_path"]] = row["manifest_hash"]
    files, runs = {}, {}
    for original, manifest_hash in refs.items():
        path = Path(original).resolve()
        if not path.is_relative_to(artifact_root):
            raise ValueError("run is outside artifact root")
        relative = path.relative_to(artifact_root).as_posix()
        manifest = verify_run(path, manifest_hash)
        bundle = verify_bundle(path / "evidence", manifest["files"]["evidence/manifest.json"])
        pinned = {**manifest["files"], "run.json": manifest_hash}
        pinned.update({f"evidence/blobs/{r['content_sha256']}.json": r["content_sha256"]
                       for r in bundle["records"]})
        for name, expected in pinned.items():
            content = read_verified(_safe(path, name), expected)
            backup_name = f"artifacts/{relative}/{name}"
            files[backup_name] = write_once(_safe(destination, backup_name), content)
        runs[original] = {"relative": relative, "manifest_hash": manifest_hash}
    # Make the snapshot a single file with no WAL sidecar dependency.
    with sqlite3.connect(snapshot) as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("PRAGMA journal_mode=DELETE")
    snapshot.chmod(0o600)
    files["store.sqlite"] = digest(snapshot.read_bytes())
    return write_json_once(destination / "backup.json", {
        "schema_version": 1, "created_at": utc_now(), "files": files, "runs": runs,
        "scope": "accepted runs, report/review, task/attempt/call, evaluations, identity and access records",
    })


def restore(source: Path, expected_hash: str, destination: Path) -> Path:
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise FileExistsError("restore requires a new directory outside the backup")
    manifest = json.loads(read_verified(source / "backup.json", expected_hash))
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported backup version")
    # Check every source before creating the staging area.
    for relative, expected in manifest["files"].items():
        read_verified(_safe(source, relative), expected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.restore")
    staging.mkdir()
    staging.chmod(0o700)
    for relative, expected in manifest["files"].items():
        write_once(_safe(staging, relative), read_verified(_safe(source, relative), expected))
    db_path = staging / "store.sqlite"
    validate_database(db_path)
    for run in manifest["runs"].values():
        verify_run(_safe(staging / "artifacts", run["relative"]), run["manifest_hash"])
    with database(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        # Relocate trusted local path metadata in this isolated restored DB only.
        db.execute("DROP TRIGGER reports_no_update")
        for original, run in manifest["runs"].items():
            new_path = str(_safe(destination / "artifacts", run["relative"]))
            db.execute("UPDATE reports SET run_path=? WHERE run_path=?", (new_path, original))
            db.execute("UPDATE tasks SET result_path=? WHERE result_path=?", (new_path, original))
        db.execute("""CREATE TRIGGER reports_no_update BEFORE UPDATE ON reports
            BEGIN SELECT RAISE(ABORT, 'report versions are immutable'); END""")
        now = utc_now()
        # Restore cannot authorize an old process or automatically make billable calls.
        active = db.execute("SELECT * FROM tasks WHERE status IN ('queued','running')").fetchall()
        for task in active:
            db.execute("UPDATE tasks SET status='cancelled',error_type='RecoveryFence' WHERE id=?",
                       (task["id"],))
            if task["attempt"]:
                db.execute("UPDATE attempts SET status='cancelled' WHERE id=?", (task["attempt"],))
                db.execute("UPDATE model_calls SET status='unknown' WHERE attempt=? AND status='started'",
                           (task["attempt"],))
            db.execute("INSERT INTO task_events(task_id,at,action,detail) VALUES (?,?,?,?)",
                       (task["id"], time.time(), "recovery_fenced",
                        json_bytes({"backup_sha256": expected_hash}).decode()))
        db.execute("UPDATE identities SET revoked=1")
        db.execute("""CREATE TABLE IF NOT EXISTS recovery_events
            (at TEXT NOT NULL, backup_hash TEXT NOT NULL, fenced_tasks INTEGER NOT NULL)""")
        db.execute("INSERT INTO recovery_events VALUES (?,?,?)", (now, expected_hash, len(active)))
    db_path.chmod(0o600)
    write_json_once(staging / "recovery.json", {
        "at": utc_now(), "backup_sha256": expected_hash, "fenced_tasks": len(active),
        "credentials_revoked": True,
    })
    # Atomic activation after verification; existing destinations are never replaced.
    staging.rename(destination)
    return destination / "store.sqlite"
