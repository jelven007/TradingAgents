"""Offline control plane, workspace authorization, invoices and recovery."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.application.runs import RunScope, execute_research
from tradingagents.application.service import ResearchService
from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
from tradingagents.domain.research import ResearchMandate
from tradingagents.domain.service import CostRequest, ReviewRequest, SubmitRequest
from tradingagents.infrastructure.artifacts import write_once
from tradingagents.infrastructure.evaluations import day_start
from tradingagents.infrastructure.evidence import record_evidence
from tradingagents.infrastructure.identity import SCOPES, AuthenticationError, IdentityStore
from tradingagents.infrastructure.recovery import backup, restore
from tradingagents.infrastructure.reports import database, verify_run
from tradingagents.infrastructure.tasks import LeaseLost
from tradingagents.interfaces.api import make_server


def request_body():
    return {
        "workspace": "research", "experiment": "control", "template": "daily",
        "mandate": {"ticker": "NVDA", "analysis_date": "2026-01-09", "benchmark": "SPY",
                    "prediction_horizon_trading_days": 5, "quote_currency": "USD",
                    "valid_until": "2099-01-01"},
    }


@pytest.fixture
def service(tmp_path):
    return ResearchService(tmp_path / "db", tmp_path / "artifacts", {
        "research": {"daily": {"config": {
            "research_policy": {"approved_tickers": ["NVDA"]},
            "source_licenses": {"test": "fixture-license"}, "private_setting": "hidden-secret",
        }}},
    })


def principal(service, subject="author", workspace="research", scopes=SCOPES):
    _, token = service.identities.issue(subject, workspace, scopes)
    return service.identities.authenticate(token)


class FixtureGraph:
    def __init__(self, config, **kwargs):
        self.config = config

    def propagate(self, ticker, date, **kwargs):
        record_evidence("test", "verified_market_facts", {}, {
            "ticker": ticker, "as_of_date": date, "price_date": date, "currency": "USD",
            "values": {"Open": 100, "High": 110, "Low": 90, "Close": 105, "Volume": 1000},
        })
        return {"company_of_interest": ticker, "trade_date": date,
                "research_mandate": self.config["research_mandate"],
                "final_rating": "Buy", "final_trade_decision": "**Rating**: Buy"}, "Buy"

    def save_reports(self, state, ticker, path):
        write_once(path / "complete_report.md", b"Fixed fixture research draft")

    def run_settings(self):
        return {"fixture": True}


def accepted(service, author, *, graph_factory=FixtureGraph):
    task = service.submit(author, SubmitRequest.model_validate(request_body()), "same")["id"]
    row = service.tasks.claim("fixture")
    assert row["id"] == task
    service.tasks.reserve_call(task, row["attempt"], "fixture-call", "fixture-model")
    service.tasks.finish_call("fixture-call", usage={"input_tokens": 100, "output_tokens": 10})
    result = execute_research(
        service.root, RunScope("research", "control", task, row["attempt"]),
        ResearchMandate.model_validate(row["payload"]["mandate"]), row["payload"]["config"],
        graph_factory=graph_factory, expected_implementation=row["implementation"],
    )
    service.tasks.complete(task, row["attempt"], result.path, result.manifest_sha256)
    return task


def test_auth_expiry_revocation_normalization_and_hash_storage(tmp_path):
    now = [100.0]
    identities = IdentityStore(tmp_path / "db", clock=lambda: now[0])
    identity, token = identities.issue(" Author ", "research", ["task:read"], ttl_seconds=2)
    assert identities.authenticate(token).subject == "author"
    with database(identities.path) as db:
        assert db.execute("SELECT token_hash FROM identities").fetchone()[0] != token
    now[0] = 103
    with pytest.raises(AuthenticationError):
        identities.authenticate(token)
    now[0] = 100
    identities.revoke(identity)
    with pytest.raises(AuthenticationError):
        identities.authenticate(token)
    with pytest.raises(ValueError):
        identities.issue("author", "research", ["superuser"])


def test_workspace_scope_redaction_review_controls_and_invoice(service):
    author, reviewer, operator = (principal(service, s) for s in ("author", "reviewer", "ops"))
    outsider = principal(service, "outsider", "other")
    task = accepted(service, author)
    report = service.register(author, task)["id"]
    assert service.register(author, task)["id"] == report
    for action in (lambda: service.task(outsider, task),
                   lambda: service.report(outsider, report),
                   lambda: service.cancel(outsider, task),
                   lambda: service.register(outsider, task),
                   lambda: service.review(outsider, report, ReviewRequest(action="approved", reason="x")),
                   lambda: service.reconcile(outsider, "fixture-call",
                                             CostRequest(amount_microusd=12, invoice_ref="fixture"))):
        with pytest.raises(PermissionError):
            action()
    public = service.task(author, task)
    assert "hidden-secret" not in json.dumps(public) and "result_path" not in public
    with pytest.raises(PermissionError, match="own report"):
        service.review(author, report, ReviewRequest(action="approved", reason="x"))
    quality = service.report(reviewer, report)["quality"]
    service.review(reviewer, report, ReviewRequest(
        action="approved", reason="fixture verification",
        acknowledgements=tuple(i["code"] for i in quality["issues"]),
    ))
    service.control(operator, "freeze_publication", True, "fixture incident")
    with pytest.raises(ValueError, match="frozen"):
        service.review(reviewer, report, ReviewRequest(action="published", reason="release"))
    service.control(operator, "freeze_publication", False, "fixture fixed")
    service.review(reviewer, report, ReviewRequest(action="published", reason="fixture release"))
    before = service.operations(operator)
    assert before["task_total"] == before["report_total"] == before["unknown_cost_calls"] == 1
    invoice = CostRequest(amount_microusd=123, invoice_ref="fixture-line")
    service.reconcile(operator, "fixture-call", invoice)
    service.reconcile(operator, "fixture-call", invoice)
    assert service.operations(operator)["unknown_cost_calls"] == 0
    assert service.operations(operator)["invoiced_microusd"] == 123
    with pytest.raises(ValueError, match="different invoice"):
        service.reconcile(operator, "fixture-call", CostRequest(amount_microusd=124, invoice_ref="new"))
    reader = principal(service, "reader", scopes={"task:read"})
    with pytest.raises(PermissionError):
        service.operations(reader)
    with pytest.raises(PermissionError):
        service.audit(reader)
    assert any(e["outcome"] == "denied" for e in service.audit(outsider))


def test_submission_pause_quota_and_no_request_config_or_actor(service):
    author = principal(service)
    service.control(author, "pause_submissions", True, "maintenance")
    with pytest.raises(ValueError, match="paused"):
        service.submit(author, SubmitRequest.model_validate(request_body()), "a")
    service.control(author, "pause_submissions", False, "restored")
    template = service.templates["research"]["daily"]
    service.templates["research"]["daily"] = template.model_copy(update={"max_pending": 1})
    results = []

    def submit(i):
        try:
            results.append(service.submit(author, SubmitRequest.model_validate(request_body()), str(i)))
        except Exception as exc:
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(submit, range(8)))
    assert len(results) == 1
    for extra in ({"config": {"backend_url": "http://localhost"}}, {"author": "reviewer"},
                  {"limits": {"budget_microusd": 10**12}}):
        with pytest.raises(ValueError):
            SubmitRequest.model_validate({**request_body(), **extra})


def test_live_loopback_http_auth_errors_and_request_audit(service, loopback_network):
    _, token = service.identities.issue("author", "research", SCOPES)
    server = make_server(service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def call(path, body=None, credential=token):
        headers = {"Authorization": f"Bearer {credential}", "Idempotency-Key": "http-key"}
        request = Request(f"http://127.0.0.1:{server.server_port}/{path}",
                          data=json.dumps(body).encode() if body is not None else None,
                          headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        assert call("operations", credential="invalid")[0] == 401
        status, response = call("tasks", request_body())
        assert status == 200
        task = response["data"]["id"]
        assert call(f"tasks/{task}")[1]["data"]["status"] == "queued"
        assert call("tasks", {**request_body(), "author": "reviewer"})[0] == 400
        assert call("calls/unknown/reconcile", {"amount_microusd": -1, "invoice_ref": "x"})[0] == 400
        assert call(f"tasks/{task}/cancel", {})[1]["data"]["status"] == "cancelled"
        events = service.audit(service.identities.authenticate(token))
        assert any(e["request_id"] == response["request_id"] and e["action"] == "task:create"
                   for e in events)
        assert "hidden-secret" not in json.dumps(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_backup_restore_integrity_reports_costs_and_old_attempt_fence(service, tmp_path):
    author = principal(service)
    task = accepted(service, author)
    report = service.register(author, task)["id"]
    pending = service.tasks.submit(service.tasks.get(task)["payload"], "other", "pending")
    running = service.tasks.claim("old-worker")
    service.tasks.reserve_call(pending, running["attempt"], "inflight", "fixture")
    ref = backup(service.tasks.path, service.root, tmp_path / "backup")
    restored_path = restore(tmp_path / "backup", ref, tmp_path / "restored")
    restored = ResearchService(restored_path, tmp_path / "restored/artifacts", {})
    result = restored.tasks.get(task)
    verify_run(result["result_path"], result["manifest_hash"])
    assert restored.reports.get(report)["manifest_hash"] == service.reports.get(report)["manifest_hash"]
    assert restored.tasks.get(pending)["status"] == "cancelled"
    assert restored.tasks.get(pending)["calls"][0]["actual_microusd"] is None
    with pytest.raises(LeaseLost, match="cancelled"):
        restored.tasks.heartbeat(pending, running["attempt"])
    with database(restored_path) as db:
        assert db.execute("SELECT COUNT(*) FROM identities WHERE revoked=0").fetchone()[0] == 0
    assert service.tasks.get(pending)["status"] == "running"  # Original untouched.
    with pytest.raises(FileExistsError):
        restore(tmp_path / "backup", ref, tmp_path / "restored")
    (tmp_path / "backup/store.sqlite").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        restore(tmp_path / "backup", ref, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_managed_cli_auth_scope_and_task_commands(service, tmp_path, monkeypatch):
    _, token = service.identities.issue("author", "research", SCOPES)
    monkeypatch.setenv("TA_RESEARCH_TOKEN", token)
    runner = CliRunner()
    prefix = ["managed", "--db", str(service.tasks.path), "--artifacts", str(service.root)]
    templates = tmp_path / "templates.json"
    templates.write_text(json.dumps({"research": {"daily": {"config": {
        "research_policy": {"approved_tickers": ["NVDA"]},
    }}}}))
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request_body()))
    result = runner.invoke(app, [*prefix, "--templates", str(templates), "submit", str(request_file),
                                 "--key", "cli"])
    assert result.exit_code == 0, result.exception
    task = json.loads(result.output)["id"]
    assert runner.invoke(app, [*prefix, "task", task]).exit_code == 0
    assert runner.invoke(app, [*prefix, "cancel", task]).exit_code == 0
    monkeypatch.delenv("TA_RESEARCH_TOKEN")
    assert runner.invoke(app, [*prefix, "operations"]).exit_code != 0


def evaluation_plan(keys=("same",), mode="diagnostic"):
    return ExperimentPlan.model_validate({
        "workspace": "research", "experiment": "control", "mode": mode,
        "price_basis": "split_adjusted_close", "calendar_source": "explicit offline calendar",
        "calendar_evidence": "Declared fixture sessions; not a built-in exchange calendar",
        "samples": [{"key": key, "mandate": request_body()["mandate"],
                     "sessions": ["2026-01-12", "2026-01-13", "2026-01-14",
                                  "2026-01-15", "2026-01-16", "2026-01-20"]} for key in keys],
    })


def evaluation_observation(exit_session="2026-01-20", entry="100"):
    return ObservationInput.model_validate({
        "entry_session": "2026-01-12", "exit_session": exit_session,
        "asset": {"symbol": "NVDA", "currency": "USD", "basis": "split_adjusted_close",
                  "entry": entry, "exit": "110"},
        "benchmark": {"symbol": "SPY", "currency": "USD", "basis": "split_adjusted_close",
                      "entry": "200", "exit": "210"},
        "source": "fixture prices", "source_payload": "offline matched USD prices",
    })


def test_experiment_plan_time_gate_template_freeze_and_atomic_sample_admission(service):
    author = principal(service)
    with pytest.raises(ValueError, match="precede every"):
        service.plan_experiment(author, evaluation_plan(mode="prospective"))
    service.evaluations.clock = lambda: day_start("2026-01-08")
    plan = service.plan_experiment(author, evaluation_plan(mode="prospective"))
    assert service.plan_experiment(author, evaluation_plan(mode="prospective"))["id"] == plan["id"]
    assert plan["historical_model_knowledge"] == "unknown"
    with pytest.raises(ValueError, match="different frozen"):
        service.plan_experiment(author, evaluation_plan())
    with pytest.raises(ValueError, match="planned sample"):
        service.submit(author, SubmitRequest.model_validate(request_body()), "unplanned")
    original = service.templates["research"]["daily"]
    service.templates["research"]["daily"] = original.model_copy(update={
        "config": {**original.config, "output_language": "changed"},
    })
    with pytest.raises(ValueError, match="template changed"):
        service.submit(author, SubmitRequest.model_validate(request_body()), "same")
    service.templates["research"]["daily"] = original
    service.evaluations.clock = lambda: day_start("2026-01-09")

    def submit(subject):
        try:
            return service.submit(principal(service, subject),
                                  SubmitRequest.model_validate(request_body()), "same")
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, [f"author{i}" for i in range(8)]))
    assert sum(r is not None for r in results) == 1
    service.evaluations.clock = lambda: day_start("2026-01-12")
    with pytest.raises(ValueError, match="precede the observation"):
        service.submit(author, SubmitRequest.model_validate(request_body()), "same")


def test_prospective_prediction_windows_immutable_observations_and_withdrawal(
    service, monkeypatch,
):
    # All historical timestamps here are an explicit synthetic-clock exercise.
    author, reviewer = principal(service), principal(service, "reviewer")
    now = [day_start("2026-01-08")]
    service.evaluations.clock = lambda: now[0]
    plan = service.plan_experiment(author, evaluation_plan(mode="prospective"))
    service.tasks.clock = lambda: day_start("2026-01-09") + 3600
    monkeypatch.setattr("tradingagents.application.runs.utc_now", lambda: "2026-01-09T20:00:00+00:00")
    monkeypatch.setattr("tradingagents.infrastructure.reports.utc_now", lambda: "2026-01-09T21:00:00+00:00")
    task = accepted(service, author)
    report = service.register(author, task)["id"]
    now[0] = day_start("2026-01-09") + 22 * 3600
    with pytest.raises(ValueError, match="published before"):
        service.register_prediction(author, plan["id"], task, report)
    quality = service.report(reviewer, report)["quality"]
    service.review(reviewer, report, ReviewRequest(
        action="approved", reason="Synthetic-clock fixture review",
        acknowledgements=tuple(i["code"] for i in quality["issues"]),
    ))
    service.review(reviewer, report, ReviewRequest(action="published", reason="Fixture release"))
    prediction = service.register_prediction(author, plan["id"], task, report)
    with pytest.raises(ValueError, match="unfinished"):
        service.observe(author, prediction["id"], evaluation_observation("2026-01-13"))
    now[0] = day_start("2026-01-14")
    assert service.register_prediction(author, plan["id"], task, report)["sha256"] == prediction["sha256"]
    interim = service.observe(author, prediction["id"], evaluation_observation("2026-01-13"))
    assert interim["result"]["window"] == "interim"
    summary = service.experiment(author, plan["id"])
    assert summary["interim_samples"] == summary["pending_samples"] == 1
    assert summary["final_samples"] == 0
    now[0] = day_start("2026-01-21")
    with pytest.raises(ValueError, match="identical entry"):
        service.observe(author, prediction["id"], evaluation_observation(entry="101"))
    final = service.observe(author, prediction["id"], evaluation_observation())
    assert final["result"]["excess_return"] == "0.05"
    assert service.observe(author, prediction["id"], evaluation_observation())["id"] == final["id"]
    with pytest.raises(ValueError, match="different immutable"):
        service.observe(author, prediction["id"], evaluation_observation(entry="101"))
    service.review(reviewer, report, ReviewRequest(action="withdrawn", reason="Fixture withdrawal"))
    assert service.prediction(author, prediction["id"])["report_status_at_registration"] == "published"
    summary = service.experiment(author, plan["id"])
    assert summary["final_samples"] == 1 and summary["report_statuses"]["withdrawn"] == 1
    for table in ("experiments", "predictions", "observations"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"), database(service.tasks.path) as db:
            db.execute(f"UPDATE {table} SET sha256='tamper'")


def test_diagnostic_denominator_review_failures_pending_and_recovery(service, tmp_path):
    author = principal(service)
    plan = service.plan_experiment(author, evaluation_plan(("same", "failed", "cancelled", "absent")))

    class ReviewGraph(FixtureGraph):
        def propagate(self, ticker, date, **kwargs):
            state, _ = super().propagate(ticker, date, **kwargs)
            state["final_rating"] = "REVIEW"
            state["final_trade_decision"] = "Evidence gap; no rating"
            return state, "REVIEW"

    task = accepted(service, author, graph_factory=ReviewGraph)
    report = service.register(author, task)["id"]
    prediction = service.register_prediction(author, plan["id"], task, report)
    service.observe(author, prediction["id"], evaluation_observation())
    failed = service.submit(author, SubmitRequest.model_validate(request_body()), "failed")["id"]
    row = service.tasks.claim("fixture")
    service.tasks.fail(failed, row["attempt"], "FixtureFailure")
    cancelled = service.submit(author, SubmitRequest.model_validate(request_body()), "cancelled")["id"]
    service.cancel(author, cancelled)
    summary = service.experiment(author, plan["id"])
    assert summary["planned_total"] == 4 and summary["task_total"] == 3
    assert summary["not_submitted"] == 1 and summary["pending_samples"] == 3
    assert summary["task_statuses"]["failed"] == summary["task_statuses"]["cancelled"] == 1
    assert summary["rating_counts"]["REVIEW"] == 1 and prediction["mode"] == "diagnostic"
    assert prediction["quality_status"] == "blocked"
    assert "Sharpe" in summary["assessment_scope"] and "strategy_nav" not in summary
    snapshot = backup(service.tasks.path, service.root, tmp_path / "eval-backup")
    restored_path = restore(tmp_path / "eval-backup", snapshot, tmp_path / "eval-restored")
    restored = ResearchService(restored_path, tmp_path / "eval-restored/artifacts", {})
    restored_author = principal(restored)
    assert restored.prediction(restored_author, prediction["id"]) == service.prediction(author, prediction["id"])
    assert restored.experiment(restored_author, plan["id"]) == summary
    with database(service.tasks.path) as db:
        db.execute("DROP TRIGGER observations_no_update")
        db.execute("UPDATE observations SET body='{}'")
    with pytest.raises(ValueError, match="integrity"):
        service.prediction(author, prediction["id"])
    with pytest.raises(ValueError, match="integrity"):
        backup(service.tasks.path, service.root, tmp_path / "bad-eval-backup")


def test_evaluation_loopback_http_scope_injection_and_cli(service, loopback_network, tmp_path, monkeypatch):
    author = principal(service)
    _, token = service.identities.issue("author", "research", SCOPES)
    _, outsider = service.identities.issue("outsider", "other", SCOPES)
    task = accepted(service, author)
    report = service.register(author, task)["id"]
    server = make_server(service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def call(path, body=None, credential=token):
        request = Request(f"http://127.0.0.1:{server.server_port}/{path}",
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={"Authorization": f"Bearer {credential}"})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        assert call("experiments", {**evaluation_plan().model_dump(mode="json"), "actor": "reviewer"})[0] == 400
        status, data = call("experiments", evaluation_plan().model_dump(mode="json"))
        assert status == 200
        experiment = data["data"]["id"]
        assert call(f"experiments/{experiment}", credential=outsider)[0] == 403
        status, data = call(f"experiments/{experiment}/predictions", {"task_id": task, "report_id": report})
        assert status == 200
        prediction = data["data"]["id"]
        assert call(f"predictions/{prediction}", credential=outsider)[0] == 403
        body = evaluation_observation().model_dump(mode="json")
        assert call(f"predictions/{prediction}/observations", body, credential=outsider)[0] == 403
        assert call(f"predictions/{prediction}/observations", body)[0] == 200
        assert call(f"experiments/{experiment}")[1]["data"]["final_samples"] == 1
        monkeypatch.setenv("TA_RESEARCH_TOKEN", token)
        runner = CliRunner()
        prefix = ["managed", "--db", str(service.tasks.path), "--artifacts", str(service.root)]
        for command, identity in (("experiment", experiment), ("prediction", prediction)):
            result = runner.invoke(app, [*prefix, command, identity])
            assert result.exit_code == 0, result.exception
        observation_file = tmp_path / "observation.json"
        observation_file.write_text(json.dumps(body))
        result = runner.invoke(app, [*prefix, "observe", prediction, str(observation_file)])
        assert result.exit_code == 0, result.exception
        limited = principal(service, "reader", scopes={"task:read"})
        with pytest.raises(PermissionError):
            service.prediction(limited, prediction)
        assert "hidden-secret" not in json.dumps(service.experiment(author, experiment))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_prospective_rejects_existing_tasks_and_late_generated_reports(service, monkeypatch):
    author, reviewer = principal(service), principal(service, "reviewer")
    service.evaluations.clock = lambda: day_start("2026-01-08")
    plan = service.plan_experiment(author, evaluation_plan(mode="prospective"))
    task = accepted(service, author)  # Generated now, after the planned historical entry.
    report = service.register(author, task)["id"]
    monkeypatch.setattr("tradingagents.infrastructure.reports.utc_now", lambda: "2026-01-09T21:00:00+00:00")
    quality = service.report(reviewer, report)["quality"]
    service.review(reviewer, report, ReviewRequest(
        action="approved", reason="Fixture only",
        acknowledgements=tuple(i["code"] for i in quality["issues"]),
    ))
    service.review(reviewer, report, ReviewRequest(action="published", reason="Fixture only"))
    service.evaluations.clock = lambda: day_start("2026-01-09") + 22 * 3600
    with pytest.raises(ValueError, match="too late"):
        service.register_prediction(author, plan["id"], task, report)
    with database(service.tasks.path) as db:
        db.execute("DROP TRIGGER experiments_no_delete")
        db.execute("DELETE FROM experiments")
    service.evaluations.clock = lambda: day_start("2026-01-08")
    with pytest.raises(ValueError, match="existing experiment tasks"):
        service.plan_experiment(author, evaluation_plan(mode="prospective"))
    diagnostic = service.plan_experiment(author, evaluation_plan(("not-submitted",)))
    summary = service.experiment(author, diagnostic["id"])
    assert summary["unplanned_task_total"] == summary["not_submitted"] == 1
