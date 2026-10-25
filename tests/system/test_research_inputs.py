"""Editable profiles, frozen run options, valuation binding and safe field errors."""

import json
import threading
from copy import deepcopy
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tradingagents.application.demo import DemoGraph, DemoService
from tradingagents.application.runs import RunScope, execute_research
from tradingagents.application.service import ResearchService
from tradingagents.application.worker import BudgetCallback
from tradingagents.domain.model_settings import SettingsConflict
from tradingagents.domain.research_settings import InputError, ResearchSettingsInput
from tradingagents.domain.service import SubmitRequest
from tradingagents.infrastructure.identity import SCOPES, Principal
from tradingagents.infrastructure.reports import database
from tradingagents.interfaces.api import make_server


def request_data(**mandate):
    return {
        "workspace": "demo", "template": "synthetic-demo", "experiment": "input-test",
        "mandate": {"ticker": "NVDA", "analysis_date": "2026-10-09", "benchmark": "SPY",
                    "quote_currency": "USD", "prediction_horizon_trading_days": 5,
                    "valid_until": "2099-01-01", **mandate},
    }


def profile_data(service, principal, name=None):
    entry = service.research_profiles(principal)["templates"][0]
    version = entry.pop("version")
    entry.pop("source")
    if name:
        entry.update(name=name, title="中文模板", description="配置测试")
        version = 0
    return {"expected_version": version, "base_template": "synthetic-demo", "profile": entry}


@pytest.mark.parametrize("round_number", [1, 2])
def test_configuration_version_scope_restart_and_frozen_options(tmp_path, round_number):
    service = DemoService(tmp_path / "demo")
    author = Principal("author", "demo", SCOPES)
    reader = Principal("reader", "demo", frozenset({"settings:read"}))
    data = profile_data(service, author, f"configured-{round_number}")
    data["profile"]["tickers"] = ["NVDA", "AAPL", "BTC-USD"]
    data["profile"]["defaults"].update(ticker="BTC-USD", quote_currency="EUR", benchmark="QQQ",
                                      asset_type="crypto", purpose="event_research",
                                      prediction_horizon_trading_days=3, valid_days=90)
    result = service.save_research_profile(author, ResearchSettingsInput.model_validate(data))
    assert result["version"] == 1
    with pytest.raises(PermissionError):
        service.save_research_profile(reader, ResearchSettingsInput.model_validate(data))
    with pytest.raises(SettingsConflict):
        service.save_research_profile(author, ResearchSettingsInput.model_validate(data))
    with pytest.raises(PermissionError):
        service.research_profiles(Principal("outside", "outside", frozenset()))
    recovered = DemoService(tmp_path / "demo")
    configured = next(t for t in recovered.session(author)["templates"] if t["name"] == result["name"])
    assert configured["source"] == "配置" and configured["defaults"]["valid_days"] == 90
    assert configured["tickers"] == ["NVDA", "AAPL", "BTC-USD"]
    raw = request_data(ticker="BTC-USD", quote_currency="EUR", benchmark="QQQ", asset_type="crypto")
    raw["template"] = result["name"]
    raw["options"] = {"selected_analysts": ["market", "news"], "max_calls": 5,
                      "max_seconds": 60, "max_output_tokens": 600, "budget_microusd": 7000}
    task_id = recovered.submit(author, SubmitRequest.model_validate(raw), "frozen")["id"]
    before = recovered.tasks.get(task_id)["payload"]
    assert before["selected_analysts"] == ["market", "news"]
    assert before["config"]["max_tokens"] == 600
    assert before["limits"]["budget_microusd"] == 7000
    update = deepcopy(data)
    update["expected_version"] = 1
    update["profile"]["defaults"]["benchmark"] = "^HSI"
    recovered.save_research_profile(author, ResearchSettingsInput.model_validate(update))
    assert recovered.tasks.get(task_id)["payload"] == before
    assert DemoService(tmp_path / "demo").session(author)["templates"][-1]["version"] == 2
    with database(recovered.tasks.path) as db, pytest.raises(Exception, match="immutable"):
        db.execute("UPDATE research_revisions SET payload='{}'")


@pytest.mark.parametrize("currency,asset,purpose", [
    ("USD", "stock", "general_research"), ("EUR", "crypto", "event_research"),
    ("CNY", "stock", "portfolio_review"), ("HKD", "crypto", "portfolio_review"),
])
def test_each_supported_mandate_executes_with_actual_selected_stages(
    tmp_path, monkeypatch, currency, asset, purpose,
):
    service, principal = DemoService(tmp_path / "demo"), Principal("author", "demo", SCOPES)
    monkeypatch.setattr("tradingagents.application.demo.time.sleep", lambda _: None)
    raw = request_data(quote_currency=currency, asset_type=asset, purpose=purpose)
    raw["options"] = {"selected_analysts": ["news"], "max_calls": 4, "max_output_tokens": 900}
    if purpose == "portfolio_review":
        raw["portfolio"] = {"currency": currency, "cash": 10000,
                            "positions": [{"ticker": "NVDA", "quantity": 2, "average_price": 90}]}
        raw["allocation_valuation"] = {"ticker": "NVDA", "currency": currency,
                                      "valuation_date": "2026-10-09", "price": "100",
                                      "equity": "10000", "current_units": "2", "change_units": "1"}
    request = SubmitRequest.model_validate(raw)
    task = service.submit(principal, request, "stages")["id"]
    row = service.tasks.claim("worker")
    value = row["payload"]
    result = execute_research(
        service.root, RunScope("demo", request.experiment, task, row["attempt"]), request.mandate,
        value["config"], selected_analysts=value["selected_analysts"], portfolio=request.portfolio,
        allocation_valuation=request.allocation_valuation, graph_factory=DemoGraph,
        callbacks=[BudgetCallback(service.tasks, task, row["attempt"])],
        expected_implementation=row["implementation"],
    )
    service.tasks.complete(task, row["attempt"], result.path, result.manifest_sha256)
    task_row = service.task(principal, task)
    assert task_row["status"] == "succeeded" and task_row["calls"] == 4
    assert task_row["inputs"]["analysts"] == ["news"]
    assert task_row["inputs"]["limits"]["max_output_tokens"] == 900
    assert task_row["inputs"]["portfolio"] == (
        request.portfolio.model_dump(mode="json") if request.portfolio else None
    )
    assert "config" not in task_row["inputs"]
    state = json.loads((result.path / "state.json").read_text())
    assert "news_report" in state and "market_report" not in state and "fundamentals_report" not in state
    assert state["research_mandate"]["asset_type"] == asset
    assert state["research_mandate"]["quote_currency"] == currency
    quality = json.loads((result.path / "quality.json").read_text())
    assert quality["status"] == "needs_review"
    if purpose == "portfolio_review":
        calc = next(c for c in quality["calculations"] if "formula" in c)
        assert calc["target_units"] == "3" and calc["absolute_weight"] == "0.03"
        assert calc["inputs"]["evidence_sha256"] != "0" * 64
        original = json.loads((result.path / "input.json").read_text())
        assert original["allocation"] is None and original["allocation_valuation"]["price"] == "100"


@pytest.mark.parametrize("price,change,code", [
    ("101", "0", "allocation_price_mismatch"), ("100", "999", "concentration"),
    ("100", "-3", "short_position"),
])
def test_valuation_mismatch_blocks_publication(tmp_path, monkeypatch, price, change, code):
    service = DemoService(tmp_path / "demo")
    monkeypatch.setattr("tradingagents.application.demo.time.sleep", lambda _: None)
    raw = request_data(purpose="portfolio_review")
    raw["portfolio"] = {"currency": "USD", "positions": [{"ticker": "NVDA", "quantity": 2}]}
    raw["allocation_valuation"] = {"ticker": "NVDA", "currency": "USD",
                                  "valuation_date": "2026-10-09", "price": price,
                                  "equity": "10000", "current_units": "2", "change_units": change}
    request = SubmitRequest.model_validate(raw)
    _, value = service._prepare(request)
    result = execute_research(
        service.root, RunScope("demo", "test", "task", "attempt"), request.mandate, value.config,
        portfolio=request.portfolio, allocation_valuation=request.allocation_valuation,
        graph_factory=DemoGraph,
    )
    quality = json.loads((result.path / "quality.json").read_text())
    assert quality["status"] == "blocked" and code in {i["code"] for i in quality["issues"]}


@pytest.mark.parametrize("changes,field", [
    ({"mandate": {"ticker": "UNAPPROVED"}}, "mandate.ticker"),
    ({"mandate": {"analysis_date": "2099-01-01"}}, "mandate.analysis_date"),
    ({"options": {"max_calls": 11}}, "options.max_calls"),
    ({"options": {"budget_microusd": 999}}, "options.budget_microusd"),
    ({"options": {"selected_analysts": []}}, "options.selected_analysts"),
    ({"options": {"selected_analysts": ["market", "market"]}}, "options.selected_analysts"),
    ({"portfolio": {"currency": "EUR", "positions": []}}, "portfolio.currency"),
    ({"mandate": {"purpose": "portfolio_review"}}, "allocation_valuation"),
])
def test_domain_rejects_invalid_inputs_before_task_admission(tmp_path, changes, field):
    service, principal = DemoService(tmp_path / "demo"), Principal("author", "demo", SCOPES)
    raw = request_data()
    for key, value in changes.items():
        raw[key] = {**raw[key], **value} if key == "mandate" else value
    with pytest.raises(InputError) as caught:
        service.submit(principal, SubmitRequest.model_validate(raw), "invalid")
    assert caught.value.field == field
    assert service.list_tasks(principal)["total"] == 0


def test_http_field_errors_are_safe_and_configuration_routes_are_scoped(tmp_path, loopback_network):
    service = ResearchService(tmp_path / "live.sqlite", tmp_path / "artifacts", {
        "demo": {"synthetic-demo": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}},
    })
    _, token = service.identities.issue("author", "demo", SCOPES, ttl_seconds=3600)
    server = make_server(service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        bad = request_data()
        bad["mandate"]["quote_currency"] = "private-secret-currency"
        request = Request(base + "/tasks", data=json.dumps(bad).encode(), headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json", "Idempotency-Key": "bad",
        })
        with pytest.raises(HTTPError) as caught:
            opener.open(request)
        body = caught.value.read().decode()
        assert caught.value.code == 400 and "private-secret" not in body
        assert json.loads(body)["fields"][0]["field"] == "mandate.quote_currency"
        with opener.open(Request(base + "/settings/research", headers={"Authorization": "Bearer " + token})) as response:
            data = json.loads(response.read())["data"]
        assert data["options"]["asset_types"] == ["stock", "crypto"]
        assert "config" not in data["templates"][0] and "api_key" not in json.dumps(data)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
