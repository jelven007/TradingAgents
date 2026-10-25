"""Browser demo isolation and the complete execute/report/review/observe flow."""

import json
import threading
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pytest

from tradingagents.application.service import ResearchService
from tradingagents.application.worker import BudgetCallback
from tradingagents.domain.evaluation import ObservationInput
from tradingagents.domain.service import SubmitRequest
from tradingagents.infrastructure.identity import SCOPES, Principal
from tradingagents.interfaces.api import make_server


def test_report_completion_recovers_after_restart_without_duplicate_versions(tmp_path, monkeypatch):
    from tradingagents.application.demo import DemoGraph, DemoService
    from tradingagents.application.runs import RunScope, execute_research

    root = tmp_path / "demo"
    service = DemoService(root)
    author = Principal("demo-researcher", "demo", SCOPES)
    request = SubmitRequest.model_validate(payload())
    task = service.submit(author, request, "recover")["id"]
    service.tasks.request_report(task, author.subject)
    row = service.tasks.claim("worker")
    monkeypatch.setattr("tradingagents.application.demo.time.sleep", lambda _: None)
    result = execute_research(
        service.root, RunScope("demo", request.experiment, task, row["attempt"]),
        request.mandate, row["payload"]["config"], graph_factory=DemoGraph,
        callbacks=[BudgetCallback(service.tasks, task, row["attempt"])],
        expected_implementation=row["implementation"],
    )
    service.tasks.complete(task, row["attempt"], result.path, result.manifest_sha256)
    assert service.list_reports(author)["total"] == 0
    recovered = DemoService(root)
    assert recovered.list_reports(author)["total"] == 1
    report_id = recovered.task(author, task)["report_id"]
    assert report_id
    again = DemoService(root)
    assert again.task(author, task)["report_id"] == report_id
    assert sum(e["action"] == "report_registered" for e in again.tasks.get(task)["events"]) == 1


def payload(workspace="demo", template="synthetic-demo", experiment="demo-test"):
    return {
        "workspace": workspace, "template": template, "experiment": experiment,
        "mandate": {"ticker": "NVDA", "analysis_date": "2026-10-09", "benchmark": "SPY",
                    "quote_currency": "USD", "prediction_horizon_trading_days": 5,
                    "valid_until": "2099-01-01"},
    }


def test_live_start_checks_all_scopes_and_credentials_before_admission(tmp_path, monkeypatch):
    service = ResearchService(tmp_path / "db", tmp_path / "artifacts", {
        "research": {"daily": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}},
    })
    author = Principal("author", "research", SCOPES)
    data = SubmitRequest.model_validate(payload("research", "daily"))
    limited = Principal("limited", "research", frozenset({"task:create", "task:execute"}))
    with pytest.raises(PermissionError):
        service.research(limited, data, "first")
    with pytest.raises(ValueError, match="credentials"):
        service.research(author, data, "first")
    assert service.list_tasks(author)["total"] == 0
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    started = []

    def start(task_id, **kwargs):
        started.append((task_id, kwargs))

    monkeypatch.setattr(service.execution, "start", start)
    task = service.research(author, data, "first")
    assert service.research(author, data, "first")["id"] == task["id"]
    assert service.list_tasks(author)["total"] == 1
    assert started == [(task["id"], {"report_actor": "author"})] * 2


def test_callback_progress_does_not_store_prompts_or_untrusted_metadata(tmp_path):
    from tradingagents.domain.tasks import TaskInput
    from tradingagents.infrastructure.tasks import LeaseLost, TaskStore

    store = TaskStore(tmp_path / "db")
    task = store.submit(TaskInput.model_validate({
        "workspace": "research", "experiment": "test", "mandate": payload()["mandate"], "config": {},
    }), "author", "test")
    row = store.claim("worker")
    callback = BudgetCallback(store, task, row["attempt"])
    callback.on_chain_start({}, {"prompt": "secret"}, run_id="a",
                            metadata={"langgraph_node": "secret-untrusted-node"})
    for _ in range(3):
        callback.on_chain_start({}, {"prompt": "secret"}, run_id="a",
                                metadata={"langgraph_node": "Market Analyst"})
    events = store.get(task)["events"]
    assert sum(e["action"] == "stage" for e in events) == 1
    assert "secret" not in json.dumps(events)
    store.cancel(task, "author")
    with pytest.raises(LeaseLost):
        store.progress(task, row["attempt"], "Trader")


def test_demo_planned_sample_starts_from_evaluation_without_replacing_plan(tmp_path, monkeypatch):
    from tradingagents.application.demo import DemoService
    from tradingagents.domain.evaluation import ExperimentPlan

    service = DemoService(tmp_path / "demo")
    principal = Principal("demo-researcher", "demo", SCOPES)
    request = SubmitRequest.model_validate(payload())
    plan = service.plan_experiment(principal, ExperimentPlan.model_validate({
        "workspace": "demo", "experiment": request.experiment, "mode": "diagnostic",
        "price_basis": "unadjusted_close", "calendar_source": "synthetic",
        "calendar_evidence": "explicit synthetic sessions",
        "samples": [{"key": "planned", "template": request.template, "mandate": request.mandate,
                     "sessions": ["2026-10-12", "2026-10-13", "2026-10-14",
                                  "2026-10-15", "2026-10-16", "2026-10-19"]}],
    }))
    started = []
    monkeypatch.setattr(service.execution, "start", lambda task_id, **kwargs: started.append(task_id))
    task = service.research(principal, request, "planned")
    assert started == [task["id"]]
    assert service.experiment(principal, plan["id"])["task_total"] == 1
    assert service.list_experiments(principal)["total"] == 1


def test_home_demo_http_runs_persists_and_enforces_boundaries(tmp_path, loopback_network):
    live = ResearchService(tmp_path / "live.sqlite", tmp_path / "live-artifacts", {
        "research": {"daily": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}},
    })
    server = make_server(live, browser_accounts=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    cookies = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))
    base, csrf = f"http://127.0.0.1:{server.server_port}", ""

    def call(path, body=None, key=None, *, with_csrf=True, extra=None, client=opener):
        headers = {"X-Workbench-Client": "web", **(extra or {})}
        if body is not None:
            headers["Content-Type"] = "application/json"
            if with_csrf:
                headers["X-Workbench-CSRF"] = csrf
        if key:
            headers["Idempotency-Key"] = key
        request = Request(base + path, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            with client.open(request, timeout=10) as response:
                return response.status, json.loads(response.read())["data"]
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        assert call("/auth/status")[1]["demo_enabled"]
        status, session = call("/demo/enter", {})
        assert status == 200 and session["demo_mode"]
        csrf = session["csrf"]
        assert call("/tasks")[0] == 401
        assert call("/demo/settings/models")[0] == 403
        assert call("/demo/role", {"role": "admin"})[0] == 400
        assert call("/demo/research", payload(), "sample", with_csrf=False)[0] == 403
        assert call("/demo/research", payload(), "sample",
                    extra={"Origin": "https://outside.example"})[0] == 403
        status, task = call("/demo/research", payload(), "sample")
        assert status == 200
        assert call("/demo/research", payload(), "sample")[1]["id"] == task["id"]
        deadline = time.monotonic() + 30
        stages = []
        while time.monotonic() < deadline:
            row = call(f"/demo/tasks/{task['id']}")[1]
            stages.extend(row["progress"]["stages"])
            if row["report_id"] or row["status"] in {"failed", "cancelled", "timed_out"}:
                break
            threading.Event().wait(0.1)
        assert row["status"] == "succeeded", row
        assert row["report_id"] and row["calls"] == 7
        assert {"行情分析", "基本面分析", "形成研究结论"} <= set(stages)
        report_id = row["report_id"]
        report = call("/demo/reports/" + report_id)[1]
        assert "合成" in report["report_markdown"]
        assert report["quality"]["status"] == "needs_review"
        assert call(f"/demo/reports/{report_id}/review", {
            "action": "approved", "reason": "self review",
        })[0] == 403
        outsider = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        assert call("/demo/enter", {}, client=outsider)[0] == 200
        assert call(f"/demo/tasks/{task['id']}", client=outsider)[0] == 404
        status, reviewer = call("/demo/role", {"role": "reviewer"})
        assert status == 200 and reviewer["subject"] != session["subject"]
        csrf = reviewer["csrf"]
        assert call("/demo/research", payload(experiment="denied"), "denied")[0] == 403
        assert call(f"/demo/reports/{report_id}/review", {
            "action": "approved", "reason": "Only synthetic workflow review",
            "acknowledgements": [i["code"] for i in report["quality"]["issues"]],
        })[0] == 200
        assert call(f"/demo/reports/{report_id}/review", {
            "action": "published", "reason": "Local demo release",
        })[1]["status"] == "published"
        csrf = call("/demo/role", {"role": "researcher"})[1]["csrf"]
        experiment = call("/demo/experiments")[1]["items"][0]["id"]
        prediction = call(f"/demo/experiments/{experiment}/predictions", {
            "task_id": task["id"], "report_id": report_id,
        })[1]
        summary = call("/demo/experiments/" + experiment)[1]
        prices = summary["demo_observation"]
        sample = summary["experiment"]["plan"]["samples"][0]
        data = ObservationInput.model_validate({
            "entry_session": sample["sessions"][0], **prices,
            "asset": {"symbol": "NVDA", "currency": "USD", "basis": "unadjusted_close", **prices["asset"]},
            "benchmark": {"symbol": "SPY", "currency": "USD", "basis": "unadjusted_close", **prices["benchmark"]},
        }).model_dump(mode="json")
        assert call(f"/demo/predictions/{prediction['id']}/observations", data)[1]["result"]["excess_return"] == "0.05"
        assert call("/demo/experiments/" + experiment)[1]["final_samples"] == 1
        assert live.tasks.path.exists() and live.accounts.setup_required()
        assert live.list_tasks(Principal("local", "research", SCOPES))["total"] == 0
        assert call("/demo/session")[1]["subject"] == session["subject"]
        csrf = call("/demo/role", {"role": "operator"})[1]["csrf"]
        ops = call("/demo/operations")[1]
        assert ops["task_statuses"]["succeeded"] == 1 and ops["model_calls"] == 7
        assert call("/demo/auth/logout", {})[0] == 200
        assert call("/demo/session")[0] == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
