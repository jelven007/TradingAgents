"""Personal persistence, admission boundaries and honest verified report summaries."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from pydantic import ValidationError

from tradingagents.application.demo import DemoGraph, DemoService
from tradingagents.application.investor import WatchlistInput, report_brief
from tradingagents.application.runs import RunScope, execute_research
from tradingagents.application.service import ResearchService
from tradingagents.domain.research_settings import InputError
from tradingagents.domain.service import SubmitRequest
from tradingagents.infrastructure.identity import SCOPES, Principal
from tradingagents.infrastructure.reports import database, verify_run
from tradingagents.interfaces.api import make_server


def change(service, principal, action="add", symbol="NVDA", note=""):
    return service.change_watchlist(principal, WatchlistInput(action=action, symbol=symbol, note=note))


def test_watchlist_notes_identity_workspace_restart_and_removed_universe(tmp_path):
    configs = {w: {"daily": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}}
               for w in ("one", "two")}
    service = ResearchService(tmp_path / "db.sqlite", tmp_path / "artifacts", configs)
    a = Principal("same-name", "one", SCOPES)
    b = Principal("other", "one", SCOPES)
    c = Principal("same-name", "two", SCOPES)
    for person, text in ((a, "核实财报\n本金数据不存浏览器"), (b, "另一人"), (c, "另一空间")):
        change(service, person)
        change(service, person, "save_note", note=text)
    change(service, a, note="重复添加不能覆盖已有笔记")
    recovered = ResearchService(tmp_path / "db.sqlite", tmp_path / "artifacts", configs)
    assert recovered.investor_home(a)["watchlist"][0]["note"].startswith("核实财报\n")
    assert recovered.investor_home(b)["watchlist"][0]["note"] == "另一人"
    assert recovered.investor_home(c)["watchlist"][0]["note"] == "另一空间"
    with pytest.raises(PermissionError):
        change(service, Principal("reader", "one", frozenset({"task:read"})))
    with pytest.raises(PermissionError):
        service.investor_home(Principal("writer", "one", frozenset({"task:create"})))
    with pytest.raises(InputError):
        change(service, a, symbol="UNAPPROVED")
    with pytest.raises(InputError):
        change(service, a, "save_note", symbol="MSFT")
    configs["one"]["daily"]["config"]["research_policy"]["approved_tickers"] = []
    restricted = ResearchService(tmp_path / "db.sqlite", tmp_path / "artifacts", configs)
    assert restricted.investor_home(a)["watchlist"][0]["approved"] is False
    change(restricted, a, "save_note", note="清单改变后仍能编辑")
    change(restricted, a, "remove")
    change(restricted, a, "remove")
    assert restricted.investor_home(a)["watchlist"] == []
    assert restricted.investor_home(b)["watchlist"][0]["note"] == "另一人"


def test_catalog_access_keeps_explicit_non_catalog_watchlist_approved(tmp_path):
    configs = {"one": {"daily": {"config": {"research_policy": {
        "approved_tickers": ["NVDA", "BTC-USD"], "allow_listed_stocks": True,
    }}}}}
    service = ResearchService(tmp_path / "db.sqlite", tmp_path / "artifacts", configs)
    principal = Principal("owner", "one", SCOPES)
    change(service, principal, symbol="BTC-USD")
    assert service.investor_home(principal)["watchlist"][0]["approved"] is True
    configs["one"]["daily"]["config"]["research_policy"]["approved_tickers"] = ["NVDA"]
    restricted = ResearchService(tmp_path / "db.sqlite", tmp_path / "artifacts", configs)
    assert restricted.investor_home(principal)["watchlist"][0]["approved"] is False


def test_watchlist_capacity_atomic_and_request_cannot_choose_owner(tmp_path):
    symbols = [f"TEST{i}" for i in range(103)]
    service = ResearchService(tmp_path / "db.sqlite", tmp_path / "artifacts", {
        "one": {"daily": {"config": {"research_policy": {"approved_tickers": symbols}}}},
    })
    p = Principal("owner", "one", SCOPES)
    for symbol in symbols[:99]:
        change(service, p, symbol=symbol)

    def add(symbol):
        try:
            change(service, p, symbol=symbol)
            return True
        except InputError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(add, symbols[99:])) == 1
    assert len(service.investor_home(p)["watchlist"]) == 100
    assert service.session(p)["instruments"][0]["name"] == "TEST0"
    for bad in ({"subject": "someone"}, {"workspace": "two"}, {"note": "a" * 4001}):
        with pytest.raises(ValidationError):
            WatchlistInput.model_validate({"action": "add", "symbol": "NVDA", **bad})


def demo_report(service, principal, monkeypatch, **mandate):
    monkeypatch.setattr("tradingagents.application.demo.time.sleep", lambda _: None)
    request = SubmitRequest.model_validate({
        "workspace": "demo", "template": "synthetic-demo", "experiment": "brief-test",
        "mandate": {"ticker": "NVDA", "analysis_date": "2026-10-09", "benchmark": "SPY",
                    "quote_currency": "USD", "prediction_horizon_trading_days": 5,
                    "valid_until": "2099-01-01", **mandate},
    })
    _, task = service._prepare(request)
    run = execute_research(service.root, RunScope("demo", "brief-test", "task", "attempt"),
                           request.mandate, task.config, graph_factory=DemoGraph)
    report_id = service.reports.register(run.path, run.manifest_sha256, principal.subject)
    return report_id, run


def test_brief_exact_excerpt_missing_data_price_and_manifest_integrity(tmp_path, monkeypatch):
    service, p = DemoService(tmp_path / "demo"), Principal("author", "demo", SCOPES)
    report_id, run = demo_report(service, p, monkeypatch)
    report = service.report(p, report_id)
    state = json.loads((run.path / "state.json").read_text())
    brief = report["brief"]
    assert brief["synthetic"] is True
    assert brief["price"]["close"] == "100" and brief["price"]["currency"] == "USD"
    assert brief["price"]["price_date"] == "2026-10-09"
    assert brief["excerpts"][0]["text"] == state["final_trade_decision"]
    assert brief["excerpts"][1]["text"] == state["investment_plan"]
    assert all(not e["provided"] and not e["text"] for e in brief["excerpts"][2:])
    assert brief["publication_times_known"] is False
    manifest = verify_run(run.path, run.manifest_sha256)
    for code in ("conflicting_prices", "unverified_currency", "stale_price", "future_price",
                 "currency_mismatch", "invalid_market_facts", "missing_verified_prices"):
        quality = deepcopy(report["quality"])
        quality["issues"].append({"code": code, "severity": "block", "detail": "test"})
        assert report_brief(run.path, manifest, report["mandate"], quality)["price"] is None
    with pytest.raises(PermissionError):
        service.report(Principal("other", "outside", SCOPES), report_id)
    (run.path / "state.json").write_text("{}")
    with pytest.raises(ValueError):
        service.report(p, report_id)


def test_own_recent_is_not_workspace_recent_and_old_watch_has_actual_latest(tmp_path):
    service, p = DemoService(tmp_path / "demo"), Principal("me", "demo", SCOPES)
    other = Principal("other", "demo", SCOPES)
    request = {"workspace": "demo", "template": "synthetic-demo", "experiment": "recent",
               "mandate": {"ticker": "NVDA", "analysis_date": "2026-10-09",
                           "benchmark": "SPY", "valid_until": "2099-01-01",
                           "quote_currency": "USD", "prediction_horizon_trading_days": 5}}
    own = service.submit(p, SubmitRequest.model_validate(request), "my")["id"]
    service.submit(other, SubmitRequest.model_validate(request), "other")
    change(service, p)
    assert [t["id"] for t in service.investor_home(p)["recent"]] == [own]
    assert service.investor_home(p)["watchlist"][0]["latest_task"]["id"] == own
    with database(service.tasks.path) as db:
        original = dict(db.execute("SELECT * FROM tasks WHERE id=?", (own,)).fetchone())
        payload = json.loads(original["payload"])
        payload["mandate"]["ticker"] = "AAPL"
        # Trusted fixture adds history, without invoking or paying for a model.
        for n in range(101):
            row = {**original, "id": f"recent-{n}", "idem_key": f"recent-{n}",
                   "created": original["created"] + n + 1, "payload": json.dumps(payload)}
            db.execute(f"INSERT INTO tasks ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                       tuple(row.values()))
    home = service.investor_home(p)
    assert len(home["recent"]) == 8 and own not in [t["id"] for t in home["recent"]]
    assert home["watchlist"][0]["latest_task"]["id"] == own


def test_http_scopes_strict_input_and_demo_live_isolation(tmp_path, loopback_network):
    service = ResearchService(tmp_path / "live.sqlite", tmp_path / "artifacts", {
        "one": {"daily": {"config": {"research_policy": {"approved_tickers": ["NVDA"]}}}},
    })
    _, token = service.identities.issue("me", "one", SCOPES, ttl_seconds=3600)
    server = make_server(service, browser_accounts=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))

    def call(path, body=None, credential=token):
        req = Request(f"http://127.0.0.1:{server.server_port}" + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"})
        try:
            with opener.open(req) as response:
                return response.status, json.loads(response.read())
        except HTTPError as err:
            return err.code, json.loads(err.read())
    try:
        assert call("/watchlist", {"action": "add", "symbol": "nvda"})[0] == 200
        assert call("/watchlist")[1]["data"]["watchlist"][0]["symbol"] == "NVDA"
        assert call("/watchlist", {"action": "add", "symbol": "NVDA", "subject": "victim"})[0] == 400
        _, read_token = service.identities.issue("reader", "one", {"task:read"}, ttl_seconds=3600)
        assert call("/watchlist", credential=read_token)[1]["data"]["watchlist"] == []
        assert call("/watchlist", {"action": "remove", "symbol": "NVDA"}, read_token)[0] == 403
        assert call("/watchlist", credential="bad")[0] == 401
        demo = DemoService(tmp_path / "separate-demo")
        dp = Principal("me", "demo", SCOPES)
        assert demo.investor_home(dp)["watchlist"] == []
        change(demo, dp)
        assert service.investor_home(Principal("me", "one", SCOPES))["watchlist"][0]["note"] == ""
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
