"""Scoped research facade shared by the local HTTP and CLI interfaces."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
from tradingagents.domain.quality import ResearchPolicy
from tradingagents.domain.service import CostRequest, ResearchTemplate, ReviewRequest, SubmitRequest
from tradingagents.domain.tasks import TaskInput
from tradingagents.infrastructure.artifacts import component
from tradingagents.infrastructure.evaluations import EvaluationStore, template_fingerprint
from tradingagents.infrastructure.identity import IdentityStore, Principal
from tradingagents.infrastructure.reports import ReportStore, database, verify_run
from tradingagents.infrastructure.tasks import BudgetExceeded, TaskStore


class ResearchService:
    def __init__(self, db_path: Path, root: Path, templates: dict):
        self.root = Path(root).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, mode=0o700)
        self.tasks = TaskStore(db_path)
        self.reports = ReportStore(db_path)
        self.identities = IdentityStore(db_path)
        self.evaluations = EvaluationStore(db_path)
        Path(db_path).chmod(0o600)
        self.templates = {
            component(workspace): {component(name): ResearchTemplate.model_validate(deepcopy(value))
                                   for name, value in entries.items()}
            for workspace, entries in templates.items()
        }
        for entries in self.templates.values():
            for name, template in entries.items():
                cfg = {**deepcopy(DEFAULT_CONFIG), **deepcopy(template.config)}
                ResearchPolicy.model_validate(cfg.get("research_policy", {}))
                entries[name] = template.model_copy(update={"config": cfg})
        with database(db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS controls (
                    workspace TEXT NOT NULL, kind TEXT NOT NULL, enabled INTEGER NOT NULL,
                    actor TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(workspace,kind)
                );
                CREATE TABLE IF NOT EXISTS cost_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, call_id TEXT NOT NULL UNIQUE
                    REFERENCES model_calls(id), amount_microusd INTEGER NOT NULL,
                    invoice_ref TEXT NOT NULL, actor TEXT NOT NULL, at REAL NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS cost_no_update BEFORE UPDATE ON cost_events
                    BEGIN SELECT RAISE(ABORT, 'cost reconciliation is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS cost_no_delete BEFORE DELETE ON cost_events
                    BEGIN SELECT RAISE(ABORT, 'cost reconciliation is immutable'); END;
            """)

    def authorize(self, principal: Principal, workspace: str, scope: str, object_id=""):
        try:
            principal.require(workspace, scope)
        except PermissionError:
            self.identities.audit(principal, scope, object_id, outcome="denied")
            raise

    @staticmethod
    def _enabled(db, workspace, kind):
        row = db.execute("SELECT enabled FROM controls WHERE workspace=? AND kind=?",
                         (workspace, kind)).fetchone()
        return bool(row and row["enabled"])

    def submit(self, principal: Principal, request: SubmitRequest, idem_key: str) -> dict:
        request = SubmitRequest.model_validate(request)
        self.authorize(principal, request.workspace, "task:create")
        template = self.templates[request.workspace][request.template]
        policy = ResearchPolicy.model_validate(template.config.get("research_policy", {}))
        if request.mandate.ticker not in policy.approved_tickers:
            raise ValueError("ticker is outside the approved research universe")
        payload = TaskInput.model_validate({
            "workspace": request.workspace, "experiment": request.experiment,
            "mandate": request.mandate, "config": deepcopy(template.config),
            "selected_analysts": template.analysts, "portfolio": request.portfolio,
            "limits": template.limits,
        })

        def admission(db):
            self.evaluations.admission(db, payload, idem_key, request.template)
            if self._enabled(db, request.workspace, "pause_submissions"):
                raise ValueError("new research submissions are paused")
            rows = db.execute("SELECT status,payload FROM tasks WHERE workspace=?",
                              (request.workspace,)).fetchall()
            if sum(r["status"] in {"queued", "running"} for r in rows) >= template.max_pending:
                raise BudgetExceeded("workspace pending-task limit reached")
            admitted = sum(json.loads(r["payload"])["limits"]["budget_microusd"] for r in rows)
            if admitted + payload.limits.budget_microusd > template.workspace_budget_microusd:
                raise BudgetExceeded("workspace admitted-budget limit reached")

        task = self.tasks.submit(payload, principal.subject, idem_key, admission_guard=admission)
        self.identities.audit(principal, "task:create", task)
        return {"id": task, "status": self.tasks.get(task)["status"]}

    def task(self, principal: Principal, task_id: str) -> dict:
        row = self.tasks.get(task_id)
        self.authorize(principal, row["workspace"], "task:read", task_id)
        self.identities.audit(principal, "task:read", task_id)
        return {**{k: row[k] for k in (
            "id", "workspace", "author", "status", "created", "deadline", "attempt_count",
            "error_type", "manifest_hash",
        )}, "mandate": row["payload"]["mandate"], "calls": len(row["calls"])}

    def cancel(self, principal: Principal, task_id: str) -> dict:
        row = self.tasks.get(task_id)
        self.authorize(principal, row["workspace"], "task:cancel", task_id)
        result = self.tasks.cancel(task_id, principal.subject)
        self.identities.audit(principal, "task:cancel", task_id)
        return {"id": task_id, "status": result["status"]}

    def register(self, principal: Principal, task_id: str, *, supersedes=None) -> dict:
        row = self.tasks.get(task_id)
        self.authorize(principal, row["workspace"], "report:register", task_id)
        if row["status"] != "succeeded":
            raise ValueError("only accepted task results can become report versions")
        path = Path(row["result_path"]).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("result path is outside the configured artifact root")
        report = self.reports.register(path, row["manifest_hash"], row["author"], supersedes=supersedes)
        self.identities.audit(principal, "report:register", report)
        return {"id": report, "status": self.reports.get(report)["status"]}

    def report(self, principal: Principal, report_id: str) -> dict:
        row = self.reports.get(report_id)
        self.authorize(principal, row["workspace"], "report:read", report_id)
        path = Path(row["run_path"])
        verify_run(path, row["manifest_hash"])
        self.identities.audit(principal, "report:read", report_id)
        text_path = path / "report" / "complete_report.md"
        return {**{k: row[k] for k in (
            "id", "workspace", "author", "status", "expired", "manifest_hash", "supersedes",
        )}, "events": row["events"], "quality": json.loads((path / "quality.json").read_bytes()),
                "report_markdown": text_path.read_text() if text_path.exists() else ""}

    def review(self, principal: Principal, report_id: str, request: ReviewRequest) -> dict:
        request = ReviewRequest.model_validate(request)
        scope = {"approved": "report:review", "rejected": "report:review",
                 "published": "report:publish", "withdrawn": "report:withdraw"}[request.action]
        row = self.reports.get(report_id)
        self.authorize(principal, row["workspace"], scope, report_id)

        def guard(db):
            if request.action == "published" and self._enabled(
                db, row["workspace"], "freeze_publication",
            ):
                raise ValueError("report publication is frozen")

        result = self.reports.transition(
            report_id, request.action, principal.subject, request.reason,
            acknowledgements=request.acknowledgements, guard=guard,
        )
        self.identities.audit(principal, scope, report_id)
        return {"id": report_id, "status": result["status"]}

    def control(self, principal: Principal, kind: str, enabled: bool, reason: str) -> dict:
        self.authorize(principal, principal.workspace, "ops:control")
        if kind not in {"pause_submissions", "freeze_publication"} or not reason.strip():
            raise ValueError("supported control and reason required")
        with database(self.tasks.path) as db:
            db.execute("INSERT OR REPLACE INTO controls VALUES (?,?,?,?,?)",
                       (principal.workspace, kind, int(enabled), principal.subject, reason))
        self.identities.audit(principal, "ops:control", kind)
        return {"kind": kind, "enabled": enabled}

    def reconcile(self, principal: Principal, call_id: str, request: CostRequest) -> dict:
        request = CostRequest.model_validate(request)
        with database(self.tasks.path) as db:
            workspace = db.execute("""SELECT t.workspace FROM model_calls c
                JOIN tasks t ON t.id=c.task_id WHERE c.id=?""", (call_id,)).fetchone()
        if workspace is None:
            raise KeyError(call_id)
        self.authorize(principal, workspace["workspace"], "cost:reconcile", call_id)
        with database(self.tasks.path) as db:
            db.execute("BEGIN IMMEDIATE")
            call = db.execute("""SELECT c.*,t.workspace FROM model_calls c
                JOIN tasks t ON t.id=c.task_id WHERE c.id=?""", (call_id,)).fetchone()
            if not call:
                raise KeyError(call_id)
            if call["actual_microusd"] is not None:
                if (call["actual_microusd"], call["invoice_ref"]) != (
                    request.amount_microusd, request.invoice_ref,
                ):
                    raise ValueError("call already reconciled with a different invoice")
            else:
                db.execute("UPDATE model_calls SET actual_microusd=?,invoice_ref=? WHERE id=?",
                           (request.amount_microusd, request.invoice_ref, call_id))
                db.execute("""INSERT INTO cost_events
                    (call_id,amount_microusd,invoice_ref,actor,at) VALUES (?,?,?,?,?)""",
                           (call_id, request.amount_microusd, request.invoice_ref, principal.subject,
                            self.tasks.clock()))
        self.identities.audit(principal, "cost:reconcile", call_id)
        return {"id": call_id, "actual_microusd": request.amount_microusd}

    def plan_experiment(self, principal: Principal, plan: ExperimentPlan) -> dict:
        plan = ExperimentPlan.model_validate(plan)
        self.authorize(principal, plan.workspace, "evaluation:write")
        hashes = {}
        for sample in plan.samples:
            template = self.templates[plan.workspace][sample.template]
            policy = ResearchPolicy.model_validate(template.config.get("research_policy", {}))
            if sample.mandate.ticker not in policy.approved_tickers:
                raise ValueError("planned ticker is outside the approved universe")
            hashes[sample.key] = template_fingerprint(
                template.config, template.analysts, template.limits.model_dump(mode="json"),
            )
        result = self.evaluations.create(plan, principal.subject, hashes)
        self.identities.audit(principal, "evaluation:plan", result["id"])
        return result

    def experiment(self, principal: Principal, experiment_id: str) -> dict:
        row = self.evaluations.experiment(experiment_id)
        self.authorize(principal, row["plan"]["workspace"], "evaluation:read", experiment_id)
        result = self.evaluations.summary(experiment_id)
        # Template hashes are public; runtime configuration and paths are not.
        self.identities.audit(principal, "evaluation:read", experiment_id)
        return result

    def register_prediction(self, principal: Principal, experiment_id: str,
                            task_id: str, report_id: str) -> dict:
        experiment = self.evaluations.experiment(experiment_id)
        self.authorize(principal, experiment["plan"]["workspace"], "evaluation:write", experiment_id)
        for store, identity in ((self.tasks, task_id), (self.reports, report_id)):
            self.authorize(principal, store.get(identity)["workspace"], "evaluation:write", identity)
        result = self.evaluations.register_prediction(experiment_id, task_id, report_id,
                                                     principal.subject)
        self.identities.audit(principal, "evaluation:prediction", result["id"])
        return result

    def prediction(self, principal: Principal, prediction_id: str) -> dict:
        row = self.evaluations.prediction(prediction_id)
        experiment = self.evaluations.experiment(row["experiment_id"])
        self.authorize(principal, experiment["plan"]["workspace"], "evaluation:read", prediction_id)
        report = self.reports.get(row["report_id"])
        verify_run(Path(report["run_path"]), row["manifest_sha256"])
        self.identities.audit(principal, "evaluation:read", prediction_id)
        return row

    def observe(self, principal: Principal, prediction_id: str, data: ObservationInput) -> dict:
        row = self.evaluations.prediction(prediction_id)
        experiment = self.evaluations.experiment(row["experiment_id"])
        self.authorize(principal, experiment["plan"]["workspace"], "evaluation:write", prediction_id)
        report = self.reports.get(row["report_id"])
        verify_run(Path(report["run_path"]), row["manifest_sha256"])
        result = self.evaluations.observe(prediction_id, data, principal.subject)
        self.identities.audit(principal, "evaluation:observe", result["id"])
        return result

    def operations(self, principal: Principal) -> dict:
        self.authorize(principal, principal.workspace, "ops:read")
        with database(self.tasks.path) as db:
            tasks = db.execute("SELECT * FROM tasks WHERE workspace=?", (principal.workspace,)).fetchall()
            calls = db.execute("""SELECT c.* FROM model_calls c JOIN tasks t ON t.id=c.task_id
                WHERE t.workspace=?""", (principal.workspace,)).fetchall()
            reports = [self.reports.get(r["id"]) for r in db.execute(
                "SELECT id FROM reports WHERE workspace=?", (principal.workspace,))]
        statuses = {s: sum(t["status"] == s for t in tasks) for s in
                    ("queued", "running", "succeeded", "failed", "cancelled", "timed_out")}
        self.identities.audit(principal, "ops:read")
        return {
            "task_total": len(tasks), "task_statuses": statuses, "report_total": len(reports),
            "review_backlog": sum(r["status"] == "draft" for r in reports),
            "expired_reports": sum(r["expired"] for r in reports),
            "model_calls": len(calls),
            "reserved_microusd": sum(c["reserved_microusd"] for c in calls),
            "invoiced_microusd": sum(c["actual_microusd"] or 0 for c in calls),
            "unknown_cost_calls": sum(c["actual_microusd"] is None for c in calls),
            "call_ledger": [{k: c[k] for k in (
                "id", "task_id", "attempt", "model", "status", "reserved_microusd",
                "actual_microusd", "usage",
            )} for c in calls[-200:]],
            "cost_scope": "model calls only; data, infrastructure and review labor excluded",
        }

    def audit(self, principal: Principal) -> list[dict]:
        self.authorize(principal, principal.workspace, "audit:read")
        self.identities.audit(principal, "audit:read")
        with database(self.tasks.path) as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM access_events WHERE workspace=? ORDER BY seq DESC LIMIT 200",
                (principal.workspace,))]
