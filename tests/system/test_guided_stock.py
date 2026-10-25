"""Bounded real-route contracts, using isolated models/data for offline regression."""

import json
from datetime import UTC, datetime

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage

from tradingagents.application.guided_stock import GuidedStockGraph
from tradingagents.application.runs import RunScope, execute_research
from tradingagents.application.securities import catalog, search, security
from tradingagents.application.service import ResearchService
from tradingagents.application.worker import BudgetCallback
from tradingagents.domain.research_settings import InputError
from tradingagents.domain.service import SubmitRequest
from tradingagents.infrastructure.identity import SCOPES, Principal
from tradingagents.infrastructure.tasks import BudgetExceeded

TODAY = datetime.now(UTC).date().isoformat()
DECISION = json.dumps({
    "rating": "Hold", "conclusion": "当前资料支持继续观察，需要核实估值和未来收入增长。",
    "reasons": ["价格与成交量已留存"], "risks": ["估值存在不确定性"],
    "conditions": ["新财报收入增长明显变化时重新研究"],
}, ensure_ascii=False)


def service_at(path, listed=True):
    return ResearchService(path / "db.sqlite", path / "artifacts", {
        "one": {"daily": {"config": {"research_policy": {
            "approved_tickers": ["NVDA"], "allow_listed_stocks": listed,
        }}}},
    })


def request(**options):
    return SubmitRequest.model_validate({
        "workspace": "one", "template": "daily", "experiment": "guided",
        "mandate": {"ticker": "AAPL", "analysis_date": TODAY, "benchmark": "SPY",
                    "quote_currency": "USD", "prediction_horizon_trading_days": 20,
                    "valid_until": "2099-01-01"},
        "options": {"execution_mode": "guided_stock", "display_currency": "CNY",
                    "stock_question": "buy", **options},
    })


def facts(ticker, day, currency):
    currency = "CNY" if ticker == "USDCNY=X" else "USD"
    price = 7 if ticker == "USDCNY=X" else 100
    return {"ticker": ticker, "as_of_date": day, "price_date": day, "currency": currency,
            "values": {"Open": price, "High": price + 1, "Low": price - 1,
                       "Close": price, "Volume": 1000}}


def test_packaged_catalog_complete_search_native_currency_and_scope(tmp_path):
    meta, rows = catalog()
    assert meta["counts"] == {"US": 12885, "CN": 5576, "HK": 2810}
    assert len(rows) == sum(meta["counts"].values()) and not any("price" in r for r in rows.values())
    for query, market, symbol, currency, benchmark in [
        ("英伟达", "US", "NVDA", "USD", "SPY"), ("贵州茅台", "CN", "600519.SS", "CNY", "000300.SS"),
        ("腾讯", "HK", "0700.HK", "HKD", "^HSI"),
    ]:
        found = search(query=query, market=market)["items"]
        row = next(r for r in found if r["symbol"] == symbol)
        assert row["quote_currency"] == currency and row["benchmark"] == benchmark
    s, p = service_at(tmp_path, False), Principal("author", "one", SCOPES)
    assert s.instruments(p, query="苹果")["items"] == []
    with pytest.raises(InputError):
        s.submit(p, request(), "out-of-scope")
    with pytest.raises(PermissionError):
        s.instruments(Principal("reader", "one", frozenset()))
    assert security("NO-SUCH-STOCK") is None


def test_frozen_defaults_budget_preflight_and_currency_separation(tmp_path):
    s, p = service_at(tmp_path), Principal("author", "one", SCOPES)
    task = s.submit(p, request(), "guided")["id"]
    payload = s.tasks.get(task)["payload"]
    assert payload["mandate"]["quote_currency"] == "USD"
    assert payload["config"]["display_currency"] == "CNY"
    assert payload["config"]["selected_security"]["name"] == "苹果"
    assert "AAPL" in payload["config"]["research_policy"]["approved_tickers"]
    for options in ({"max_calls": 7}, {"budget_microusd": 3_999_999}):
        with pytest.raises(InputError, match="8"):
            s.submit(p, request(**options), "low")
    bad = request().model_dump()
    bad["mandate"]["quote_currency"] = "CNY"
    with pytest.raises(InputError, match="报价币种"):
        s.submit(p, SubmitRequest.model_validate(bad), "currency")
    recovered = service_at(tmp_path)
    assert recovered.tasks.get(task)["payload"] == payload


@pytest.mark.parametrize("mode", ["complete", "network", "parse", "budget", "partial", "truncated", "invalid_prices"])
def test_guided_output_failure_honesty_call_ledger_fx_and_integrity(tmp_path, monkeypatch, mode):
    s, p = service_at(tmp_path), Principal("author", "one", SCOPES)
    monkeypatch.setattr("tradingagents.application.guided_stock.company_data", lambda *a: {"sector": "Technology"})
    monkeypatch.setattr("tradingagents.application.guided_stock.news_data", lambda *a: {"items": []})
    outputs = ["分析价格资料", "多方观点", "反方观点", DECISION]
    if mode == "parse":
        outputs[-1] = "not JSON"
        outputs.append("still not JSON")
    model = FakeListChatModel(responses=outputs)
    if mode == "truncated":
        model = FakeMessagesListChatModel(responses=[
            AIMessage(content=text) for text in outputs[:3]
        ] + [AIMessage(content=DECISION, response_metadata={"finish_reason": "length"})] * 2)
    model_requests = []

    def factory(cfg, tier, **kwargs):
        model_requests.append((tier, cfg["max_tokens"], cfg["llm_max_retries"]))
        if mode == "budget":
            raise BudgetExceeded("budget fence")
        if mode == "partial" and tier == "quick":
            raise OSError("SECRET endpoint")
        return type("Client", (), {"get_llm": lambda self: model})()

    def data(ticker, day, currency):
        if mode == "network" and ticker == "AAPL":
            raise OSError("SECRET endpoint")
        value = facts(ticker, day, currency)
        if mode == "invalid_prices" and ticker == "AAPL":
            value["values"]["High"] = 1
        return value

    def graph_factory(**kwargs):
        return GuidedStockGraph(**kwargs, data_loader=data, llm_factory=factory)
    task_id = s.submit(p, request(), mode)["id"]
    row = s.tasks.claim("test", task_id=task_id)
    if mode == "budget":
        with pytest.raises(BudgetExceeded):
            execute_research(s.root, RunScope("one", "guided", task_id, row["attempt"]),
                             request().mandate, row["payload"]["config"], graph_factory=graph_factory)
        return
    result = execute_research(
        s.root, RunScope("one", "guided", task_id, row["attempt"]), request().mandate,
        row["payload"]["config"], graph_factory=graph_factory,
        callbacks=[BudgetCallback(s.tasks, task_id, row["attempt"])],
    )
    s.tasks.complete(task_id, row["attempt"], result.path, result.manifest_sha256)
    report_id = s.register(p, task_id)["id"]
    report = s.report(p, report_id)
    if mode == "complete":
        assert s.task(p, task_id)["calls"] == 4 and result.rating == "Hold"
        assert report["brief"]["converted_price"]["close"] == "700.00"
        assert report["brief"]["price"]["currency"] == "USD"
        # No fabricated licenses: real-route drafts remain blocked without a license.
        assert "unknown_license" in {i["code"] for i in report["quality"]["issues"]}
    else:
        assert result.rating == "Insufficient" and report["brief"]["research_status"] == "insufficient"
        assert "资料不足" in report["report_markdown"]
        assert "SECRET" not in report["report_markdown"]
        assert len(model_requests) <= 8
        if mode in {"network", "invalid_prices"}:
            assert not model_requests and s.task(p, task_id)["calls"] == 0
        if mode in {"parse", "truncated"}:
            assert s.task(p, task_id)["calls"] == 5
        if mode == "truncated":
            assert report["brief"]["data_gaps"][-1]["category"] == "output_limit"
    assert all(retries == 0 and cap <= row["payload"]["limits"]["max_output_tokens"]
               for _, cap, retries in model_requests)
    (result.path / "state.json").write_text("{}")
    with pytest.raises(ValueError):
        s.report(p, report_id)
