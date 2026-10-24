"""Append-only plans, report-bound predictions and matched-window observations."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, date, datetime, time as day_time
from pathlib import Path

from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput, evaluate_window
from tradingagents.infrastructure.artifacts import digest, json_bytes
from tradingagents.infrastructure.reports import ReportStore, database, verify_run


def day_start(value: str) -> float:
    return datetime.combine(date.fromisoformat(value), day_time(), UTC).timestamp()


def template_fingerprint(config, analysts, limits) -> str:
    effective = {**config, "llm_max_retries": 0, "max_tokens": limits["max_output_tokens"]}
    return digest(json_bytes({"config": effective, "analysts": list(analysts), "limits": limits}))


class EvaluationStore:
    def __init__(self, path: Path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.reports = ReportStore(path)
        with database(path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, workspace TEXT NOT NULL, name TEXT NOT NULL,
                    body TEXT NOT NULL, sha256 TEXT NOT NULL, UNIQUE(workspace,name)
                );
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    sample_key TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
                    report_id TEXT NOT NULL REFERENCES reports(id),
                    body TEXT NOT NULL, sha256 TEXT NOT NULL, UNIQUE(experiment_id,sample_key)
                );
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES predictions(id),
                    exit_session TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL,
                    UNIQUE(prediction_id,exit_session)
                );
            """)
            for table in ("experiments", "predictions", "observations"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                        BEFORE {operation} ON {table}
                        BEGIN SELECT RAISE(ABORT, 'evaluation records are immutable'); END""")

    @staticmethod
    def _read(row) -> dict:
        if row is None:
            raise KeyError("evaluation record")
        if digest(row["body"].encode()) != row["sha256"]:
            raise ValueError("evaluation integrity check failed")
        return {"id": row["id"], "sha256": row["sha256"], **json.loads(row["body"])}

    def experiment(self, experiment_id: str) -> dict:
        with database(self.path) as db:
            row = db.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        result = self._read(row)
        plan = ExperimentPlan.model_validate(result["plan"])
        if (row["workspace"], row["name"]) != (plan.workspace, plan.experiment):
            raise ValueError("experiment index does not match the frozen plan")
        return result

    def create(self, plan: ExperimentPlan, actor: str, template_hashes: dict) -> dict:
        plan = ExperimentPlan.model_validate(plan)
        if set(template_hashes) != {s.key for s in plan.samples}:
            raise ValueError("every planned sample needs a frozen template fingerprint")
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM experiments WHERE workspace=? AND name=?",
                             (plan.workspace, plan.experiment)).fetchone()
            if old:
                value = self._read(old)
                if value["plan"] != plan.model_dump(mode="json") or value["templates"] != template_hashes:
                    raise ValueError("experiment already has a different frozen plan")
                return value
            now = self.clock()
            if plan.mode == "prospective":
                if now >= min(day_start(s.mandate.analysis_date) for s in plan.samples):
                    raise ValueError("prospective plan must precede every daily research date")
                if any(json.loads(t["payload"])["experiment"] == plan.experiment for t in
                       db.execute("SELECT payload FROM tasks WHERE workspace=?", (plan.workspace,))):
                    raise ValueError("prospective plan cannot follow existing experiment tasks")
            identity = uuid.uuid4().hex
            body = {"plan": plan.model_dump(mode="json"), "actor": actor, "registered_at": now,
                    "templates": template_hashes,
                    "calendar_sha256": digest(json_bytes({
                        "source": plan.calendar_source, "evidence": plan.calendar_evidence,
                        "sessions": {s.key: s.sessions for s in plan.samples},
                    })),
                    "historical_model_knowledge": "unknown",
                    "provenance": "operator supplied; hashes verify retention, not source authenticity"}
            raw = json_bytes(body)
            db.execute("INSERT INTO experiments VALUES (?,?,?,?,?)",
                       (identity, plan.workspace, plan.experiment, raw.decode(), digest(raw)))
        return self.experiment(identity)

    def admission(self, db, payload, idem_key: str, template: str):
        row = db.execute("SELECT * FROM experiments WHERE workspace=? AND name=?",
                         (payload.workspace, payload.experiment)).fetchone()
        if row is None:
            return  # Existing unplanned SDK/service tasks retain their behavior.
        value = self._read(row)
        plan = ExperimentPlan.model_validate(value["plan"])
        sample = next((s for s in plan.samples if s.key == idem_key), None)
        if sample is None or sample.mandate != payload.mandate or sample.template != template:
            raise ValueError("task must match a frozen planned sample and template")
        actual = template_fingerprint(payload.config, payload.selected_analysts,
                                      payload.limits.model_dump(mode="json"))
        if value["templates"][sample.key] != actual:
            raise ValueError("experiment template changed; use a new experiment")
        if plan.mode == "prospective" and self.clock() >= day_start(sample.sessions[0]):
            raise ValueError("prospective task must precede the observation entry session")
        if any(json.loads(t["payload"])["experiment"] == payload.experiment for t in db.execute(
            "SELECT payload FROM tasks WHERE workspace=? AND idem_key=?",
            (payload.workspace, idem_key),
        )):
            raise ValueError("planned sample already belongs to another task")

    def prediction(self, prediction_id: str) -> dict:
        with database(self.path) as db:
            row = db.execute("SELECT * FROM predictions WHERE id=?", (prediction_id,)).fetchone()
            observation_rows = list(db.execute(
                "SELECT * FROM observations WHERE prediction_id=? ORDER BY exit_session",
                (prediction_id,)))
            observations = [self._read(r) for r in observation_rows]
        result = self._read(row)
        if any(row[k] != result[k] for k in ("experiment_id", "sample_key", "task_id", "report_id")):
            raise ValueError("prediction index does not match its record")
        experiment = self.experiment(row["experiment_id"])
        if result["plan_sha256"] != experiment["sha256"]:
            raise ValueError("prediction plan reference mismatch")
        report = self.reports.get(result["report_id"])
        if (report["manifest_hash"] != result["manifest_sha256"] or
                result["review_event_sha256"] not in {e["event_hash"] for e in report["events"]}):
            raise ValueError("prediction report or review reference mismatch")
        plan = ExperimentPlan.model_validate(experiment["plan"])
        sample = next(s for s in plan.samples if s.key == result["sample_key"])
        for stored, observation in zip(observation_rows, observations, strict=True):
            if observation["prediction_sha256"] != result["sha256"]:
                raise ValueError("observation prediction reference mismatch")
            data = ObservationInput.model_validate(observation["input"])
            if (stored["exit_session"] != data.exit_session or
                    digest(json_bytes(data.model_dump(mode="json"))) != observation["input_sha256"] or
                    digest(data.source_payload.encode()) != observation["source_sha256"] or
                    evaluate_window(sample, plan.price_basis, data) != observation["result"]):
                raise ValueError("observation content or calculation mismatch")
        return {**result, "observations": observations}

    def register_prediction(self, experiment_id: str, task_id: str, report_id: str, actor: str) -> dict:
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            experiment = self.experiment(experiment_id)
            plan = ExperimentPlan.model_validate(experiment["plan"])
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            report = self.reports.get(report_id)
            if task is None:
                raise KeyError(task_id)
            payload = json.loads(task["payload"])
            sample = next((s for s in plan.samples if s.key == task["idem_key"]), None)
            if (task["workspace"] != plan.workspace or payload["experiment"] != plan.experiment
                    or sample is None or payload["mandate"] != sample.mandate.model_dump(mode="json")):
                raise ValueError("prediction task is outside the frozen experiment")
            if (task["status"] != "succeeded" or task["manifest_hash"] != report["manifest_hash"]
                    or task["result_path"] != report["run_path"]):
                raise ValueError("prediction requires the accepted task's fixed report")
            fingerprint = template_fingerprint(payload["config"], payload["selected_analysts"],
                                               payload["limits"])
            if fingerprint != experiment["templates"][sample.key]:
                raise ValueError("accepted task does not match the planned template")
            manifest = verify_run(Path(report["run_path"]), report["manifest_hash"])
            old = db.execute("SELECT * FROM predictions WHERE experiment_id=? AND sample_key=?",
                             (experiment_id, sample.key)).fetchone()
            if old:
                value = self._read(old)
                if value["task_id"] != task_id or value["report_id"] != report_id:
                    raise ValueError("sample already has a fixed prediction")
                return self.prediction(old["id"])
            now = self.clock()
            if plan.mode == "prospective":
                if now >= day_start(sample.sessions[0]) or report["status"] != "published":
                    raise ValueError("prospective prediction must be published before entry")
                published = datetime.fromisoformat(report["events"][-1]["at"]).timestamp()
                completed = datetime.fromisoformat(manifest["completed_at"]).timestamp()
                if (not experiment["registered_at"] <= task["created"] <= completed <= published <= now
                        or completed < day_start(sample.mandate.analysis_date)
                        or published >= day_start(sample.sessions[0]) or report["expired"]):
                    raise ValueError("publication is too late or research has expired")
            quality = json.loads((Path(report["run_path"]) / "quality.json").read_bytes())
            body = {
                "experiment_id": experiment_id, "plan_sha256": experiment["sha256"],
                "sample_key": sample.key, "task_id": task_id, "report_id": report_id,
                "manifest_sha256": report["manifest_hash"], "rating": manifest["rating"],
                "report_status_at_registration": report["status"],
                "review_event_sha256": report["events"][-1]["event_hash"],
                "quality_status": quality["status"], "registered_at": now, "actor": actor,
                "mode": plan.mode, "historical_model_knowledge": "unknown",
            }
            raw, identity = json_bytes(body), uuid.uuid4().hex
            db.execute("INSERT INTO predictions VALUES (?,?,?,?,?,?,?)",
                       (identity, experiment_id, sample.key, task_id, report_id,
                        raw.decode(), digest(raw)))
        return self.prediction(identity)

    def observe(self, prediction_id: str, data: ObservationInput, actor: str) -> dict:
        data = ObservationInput.model_validate(data)
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            prediction = self.prediction(prediction_id)
            experiment = self.experiment(prediction["experiment_id"])
            plan = ExperimentPlan.model_validate(experiment["plan"])
            sample = next(s for s in plan.samples if s.key == prediction["sample_key"])
            result = evaluate_window(sample, plan.price_basis, data)
            # Daily closes are only accepted after the entire UTC-labelled date has ended.
            if self.clock() < day_start(data.exit_session) + 86400:
                raise ValueError("cannot observe an unfinished daily exit session")
            old = db.execute("SELECT * FROM observations WHERE prediction_id=? AND exit_session=?",
                             (prediction_id, data.exit_session)).fetchone()
            if old:
                value = self._read(old)
                if value["input"] != data.model_dump(mode="json"):
                    raise ValueError("exit session already has a different immutable observation")
                return value
            if prediction["observations"]:
                previous = prediction["observations"][0]["input"]
                if any(previous[k]["entry"] != data.model_dump(mode="json")[k]["entry"]
                       for k in ("asset", "benchmark")):
                    raise ValueError("all windows must retain identical entry prices")
            body = {"prediction_sha256": prediction["sha256"], "input": data.model_dump(mode="json"),
                    "result": result, "actor": actor, "recorded_at": self.clock(),
                    "source_sha256": digest(data.source_payload.encode()),
                    "input_sha256": digest(json_bytes(data.model_dump(mode="json")))}
            raw, identity = json_bytes(body), uuid.uuid4().hex
            db.execute("INSERT INTO observations VALUES (?,?,?,?,?)",
                       (identity, prediction_id, data.exit_session, raw.decode(), digest(raw)))
        return {"id": identity, "sha256": digest(raw), **body}

    def summary(self, experiment_id: str) -> dict:
        experiment = self.experiment(experiment_id)
        plan = ExperimentPlan.model_validate(experiment["plan"])
        with database(self.path) as db:
            tasks = [dict(r) for r in db.execute(
                "SELECT * FROM tasks WHERE workspace=?", (plan.workspace,))
                if json.loads(r["payload"])["experiment"] == plan.experiment]
            predictions = [self.prediction(r["id"]) for r in db.execute(
                "SELECT id FROM predictions WHERE experiment_id=?", (experiment_id,))]
            reports = [self.reports.get(r["id"]) for r in db.execute(
                "SELECT id,run_path FROM reports WHERE workspace=?", (plan.workspace,))
                if any(t["result_path"] == r["run_path"] for t in tasks)]
        planned = {s.key for s in plan.samples}
        samples = []
        ratings = {}
        for task in tasks:
            if task["status"] == "succeeded":
                rating = verify_run(Path(task["result_path"]), task["manifest_hash"])["rating"]
                ratings[rating] = ratings.get(rating, 0) + 1
        for sample in plan.samples:
            matched = [t for t in tasks if t["idem_key"] == sample.key]
            prediction = next((p for p in predictions if p["sample_key"] == sample.key), None)
            windows = prediction["observations"] if prediction else []
            observation_status = ("final" if any(o["result"]["window"] == "final" for o in windows)
                                  else "interim" if windows else "pending")
            samples.append({"key": sample.key, "task_ids": [t["id"] for t in matched],
                            "task_statuses": [t["status"] for t in matched] or ["not_submitted"],
                            "prediction_id": prediction["id"] if prediction else None,
                            "rating": prediction["rating"] if prediction else None,
                            "observation_status": observation_status})
        return {
            "experiment": experiment, "planned_total": len(plan.samples), "task_total": len(tasks),
            "unplanned_task_total": sum(t["idem_key"] not in planned for t in tasks),
            "ambiguous_samples": sum(len(s["task_ids"]) > 1 for s in samples),
            "not_submitted": sum(not s["task_ids"] for s in samples),
            "task_statuses": {s: sum(t["status"] == s for t in tasks) for s in
                              ("queued", "running", "succeeded", "failed", "cancelled", "timed_out")},
            "rating_counts": ratings, "report_total": len(reports),
            "report_statuses": {s: sum(r["status"] == s for r in reports) for s in
                                ("draft", "approved", "published", "rejected", "withdrawn")},
            "prediction_total": len(predictions), "samples": samples,
            "final_samples": sum(s["observation_status"] == "final" for s in samples),
            "interim_samples": sum(s["observation_status"] == "interim" for s in samples),
            "pending_samples": sum(s["observation_status"] != "final" for s in samples),
            "assessment_scope": "window coverage and retained returns; no strategy NAV or Sharpe",
        }

    def validate(self):
        with database(self.path) as db:
            experiments = [r["id"] for r in db.execute("SELECT id FROM experiments")]
            predictions = [r["id"] for r in db.execute("SELECT id FROM predictions")]
        for identity in experiments:
            self.experiment(identity)
        for identity in predictions:
            self.prediction(identity)
