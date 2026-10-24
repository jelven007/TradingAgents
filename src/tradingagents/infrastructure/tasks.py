"""SQLite task truth, fenced leases and durable model-call reservations."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from tradingagents.application.runs import implementation_versions
from tradingagents.domain.tasks import TaskInput
from tradingagents.infrastructure.artifacts import digest, json_bytes
from tradingagents.infrastructure.reports import database, verify_run


class LeaseLost(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class TaskStore:
    def __init__(self, path: Path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with database(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, author TEXT NOT NULL,
                    idem_key TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    implementation TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                    deadline REAL, attempt TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL, result_path TEXT, manifest_hash TEXT, error_type TEXT,
                    UNIQUE(workspace, author, idem_key)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    worker TEXT NOT NULL, started REAL NOT NULL, ended REAL, status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    attempt TEXT NOT NULL REFERENCES attempts(id), model TEXT NOT NULL,
                    started REAL NOT NULL, ended REAL, status TEXT NOT NULL,
                    reserved_microusd INTEGER NOT NULL, actual_microusd INTEGER,
                    usage TEXT, invoice_ref TEXT
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id),
                    at REAL NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS task_input_immutable
                    BEFORE UPDATE OF workspace,author,idem_key,payload,payload_hash,implementation,created
                    ON tasks BEGIN SELECT RAISE(ABORT, 'task input is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task_events_no_update BEFORE UPDATE ON task_events
                    BEGIN SELECT RAISE(ABORT, 'task events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS task_events_no_delete BEFORE DELETE ON task_events
                    BEGIN SELECT RAISE(ABORT, 'task events are immutable'); END;
                CREATE INDEX IF NOT EXISTS tasks_claim ON tasks(status,created);
                CREATE INDEX IF NOT EXISTS model_calls_task ON model_calls(task_id);
            """)

    def _event(self, db, task_id, action, **detail):
        db.execute("INSERT INTO task_events(task_id,at,action,detail) VALUES (?,?,?,?)",
                   (task_id, self.clock(), action, json_bytes(detail).decode()))

    def submit(self, payload: TaskInput, author: str, idem_key: str, *, admission_guard=None) -> str:
        payload = TaskInput.model_validate(payload)
        if not author.strip() or not 1 <= len(idem_key) <= 128:
            raise ValueError("author and bounded idempotency key are required")
        body = payload.model_dump(mode="json")
        # Provider retries are invisible to callback billing and are disabled.
        body["config"]["llm_max_retries"] = 0
        body["config"]["max_tokens"] = payload.limits.max_output_tokens
        encoded = json_bytes(body).decode()
        fingerprint = digest(encoded.encode())
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM tasks WHERE workspace=? AND author=? AND idem_key=?",
                             (payload.workspace, author, idem_key)).fetchone()
            if old:
                if old["payload_hash"] != fingerprint:
                    raise ValueError("idempotency key conflicts with existing task input")
                return old["id"]
            if admission_guard is not None:
                admission_guard(db)
            task_id = uuid.uuid4().hex
            db.execute("""INSERT INTO tasks
                (id,workspace,author,idem_key,payload,payload_hash,implementation,status,created)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                       (task_id, payload.workspace, author, idem_key, encoded, fingerprint,
                        json_bytes(implementation_versions()).decode(), "queued", self.clock()))
            self._event(db, task_id, "submitted", actor=author)
        return task_id

    def get(self, task_id: str) -> dict:
        with database(self.path) as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            result = dict(row)
            for field in ("payload", "implementation"):
                result[field] = json.loads(result[field])
            if digest(json_bytes(result["payload"])) != row["payload_hash"]:
                raise ValueError("task input integrity check failed")
            result["calls"] = [dict(r) for r in db.execute(
                "SELECT * FROM model_calls WHERE task_id=? ORDER BY started,id", (task_id,))]
            result["events"] = [dict(r) for r in db.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY seq", (task_id,))]
            return result

    def _active(self, db, task_id, attempt):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if (not row or row["status"] != "running" or row["attempt"] != attempt
                or row["lease_until"] <= self.clock() or row["deadline"] <= self.clock()):
            raise LeaseLost("attempt is cancelled, expired or superseded")
        return row

    def check_lease(self, task_id: str, attempt: str):
        with database(self.path) as db:
            self._active(db, task_id, attempt)

    def _reap(self, db):
        now = self.clock()
        expired = db.execute(
            "SELECT * FROM tasks WHERE status='running' AND (lease_until<=? OR deadline<=?)",
            (now, now),
        ).fetchall()
        for row in expired:
            limits = json.loads(row["payload"])["limits"]
            status = ("timed_out" if row["deadline"] <= now else
                      "failed" if row["attempt_count"] >= limits["max_attempts"] else "queued")
            self._end_attempt(db, row, "lease_expired")
            db.execute("UPDATE tasks SET status=?,error_type='LeaseExpired' WHERE id=?",
                       (status, row["id"]))
            self._event(db, row["id"], status, attempt=row["attempt"], cause="lease_expired")
        for row in db.execute(
            "SELECT id FROM tasks WHERE status='queued' AND deadline<=?", (now,),
        ).fetchall():
            db.execute("UPDATE tasks SET status='timed_out' WHERE id=?", (row["id"],))
            self._event(db, row["id"], "timed_out")

    def reap(self):
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self._reap(db)

    def claim(self, worker: str, *, lease_seconds=30, max_concurrency=2) -> dict | None:
        if lease_seconds <= 0 or max_concurrency < 1:
            raise ValueError("positive lease and concurrency required")
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            now = self.clock()
            self._reap(db)
            active = db.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]
            if active >= max_concurrency:
                return None
            row = db.execute(
                "SELECT * FROM tasks WHERE status='queued' ORDER BY created,id LIMIT 1",
            ).fetchone()
            if not row:
                return None
            attempt = uuid.uuid4().hex
            deadline = row["deadline"] or now + json.loads(row["payload"])["limits"]["max_seconds"]
            db.execute("""UPDATE tasks SET status='running', attempt=?,attempt_count=attempt_count+1,
                lease_until=?,deadline=?,error_type=NULL WHERE id=?""",
                       (attempt, now + lease_seconds, deadline, row["id"]))
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,NULL,'running')",
                       (attempt, row["id"], worker, now))
            self._event(db, row["id"], "claimed", attempt=attempt, worker=worker)
            task_id = row["id"]
        return self.get(task_id)

    def heartbeat(self, task_id: str, attempt: str, *, lease_seconds=30):
        if lease_seconds <= 0:
            raise ValueError("positive lease required")
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self._active(db, task_id, attempt)
            db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                       (self.clock() + lease_seconds, task_id))

    def _end_attempt(self, db, row, status):
        db.execute("UPDATE attempts SET ended=?,status=? WHERE id=?",
                   (self.clock(), status, row["attempt"]))
        db.execute("""UPDATE model_calls SET ended=?,status='unknown'
            WHERE attempt=? AND status='started'""", (self.clock(), row["attempt"]))

    def cancel(self, task_id: str, actor: str) -> dict:
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["status"] in {"queued", "running"}:
                if row["attempt"]:
                    self._end_attempt(db, row, "cancelled")
                db.execute("UPDATE tasks SET status='cancelled' WHERE id=?", (task_id,))
                self._event(db, task_id, "cancelled", actor=actor)
        return self.get(task_id)

    def fail(self, task_id: str, attempt: str, error_type: str):
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._active(db, task_id, attempt)
            self._end_attempt(db, row, "failed")
            db.execute("UPDATE tasks SET status='failed',error_type=? WHERE id=?",
                       (error_type, task_id))
            self._event(db, task_id, "failed", attempt=attempt, error_type=error_type)

    def complete(self, task_id: str, attempt: str, path: Path, manifest_hash: str):
        manifest = verify_run(path, manifest_hash)
        inputs = json.loads((Path(path) / "input.json").read_bytes())
        task = self.get(task_id)
        payload = task["payload"]
        expected_scope = {"workspace": payload["workspace"], "experiment": payload["experiment"],
                          "task": task_id, "attempt": attempt}
        if (inputs["scope"] != expected_scope or manifest["scope"] != expected_scope
                or inputs["mandate"] != payload["mandate"]
                or inputs["config_sha256"] != digest(json_bytes(payload["config"]))
                or inputs["portfolio"] != payload["portfolio"]
                or inputs["allocation"] != payload["allocation"]
                or inputs["analysts"] != payload["selected_analysts"]
                or manifest["implementation"] != task["implementation"]):
            raise ValueError("result does not match frozen task input/version")
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._active(db, task_id, attempt)
            if row["error_type"] == "BudgetExceeded":
                raise BudgetExceeded("cannot accept a budget-exhausted run")
            self._end_attempt(db, row, "succeeded")
            db.execute("""UPDATE tasks SET status='succeeded',result_path=?,manifest_hash=?
                WHERE id=?""", (str(Path(path).resolve()), manifest_hash, task_id))
            self._event(db, task_id, "succeeded", attempt=attempt, manifest_hash=manifest_hash)

    def reserve_call(self, task_id: str, attempt: str, call_id: str, model: str):
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._active(db, task_id, attempt)
            limits = json.loads(row["payload"])["limits"]
            calls = db.execute("SELECT * FROM model_calls WHERE task_id=?", (task_id,)).fetchall()
            used = sum(max(c["reserved_microusd"], c["actual_microusd"] or 0) for c in calls)
            reserve = limits["reserve_per_call_microusd"]
            exceeded = (row["error_type"] == "BudgetExceeded" or len(calls) >= limits["max_calls"]
                        or used + reserve > limits["budget_microusd"])
            if exceeded:
                db.execute("UPDATE tasks SET error_type='BudgetExceeded' WHERE id=?", (task_id,))
                self._event(db, task_id, "budget_exceeded", attempt=attempt)
            else:
                db.execute("""INSERT INTO model_calls
                    (id,task_id,attempt,model,started,status,reserved_microusd)
                    VALUES (?,?,?,?,?,'started',?)""",
                           (call_id, task_id, attempt, model[:200], self.clock(), reserve))
        if exceeded:
            raise BudgetExceeded("model-call reservation budget exhausted")

    def finish_call(self, call_id: str, *, usage: dict | None = None, failed=False):
        # Late usage is retained even after cancellation/reclaim; it cannot accept a result.
        safe_usage = {k: v for k, v in (usage or {}).items()
                      if k in {"input_tokens", "output_tokens", "total_tokens"}
                      and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
        with database(self.path) as db:
            db.execute("""UPDATE model_calls SET ended=?,status=?,usage=?
                WHERE id=? AND status IN ('started','unknown')""",
                       (self.clock(), "unknown" if failed else "returned",
                        json_bytes(safe_usage).decode() if safe_usage else None, call_id))
