"""The whole graph, end to end, with scripted models and no network.

Every tool-using analyst calls each of its tools once through the vendor router,
the debates and managers run, and the decision is parsed and logged. This pins
the wiring: a restructure that drops a node, a tool or an edge fails here.
"""

from __future__ import annotations

import copy
import time

import pandas as pd
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from tradingagents.agents import context, schemas
from tradingagents.agents.analysts import sentiment_analyst
from tradingagents.dataflows import router
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market, snapshot
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph

TRADE_DATE = "2026-01-09"

# Enough for every free-text reader: the PM's labelled rating and the trader's
# closing proposal line.
TEXT = "Report.\n\n**Rating**: Overweight\n\nFINAL TRANSACTION PROPOSAL: **BUY**"

STRUCTURED = {
    schemas.ResearchPlan: schemas.ResearchPlan(
        recommendation=schemas.PortfolioRating.OVERWEIGHT, rationale="r", strategic_actions="a"),
    schemas.TraderProposal: schemas.TraderProposal(action=schemas.TraderAction.BUY, reasoning="r"),
    # The thesis quotes another party's rating; the decision is still the PM's own.
    schemas.PortfolioDecision: schemas.PortfolioDecision(
        rating=schemas.PortfolioRating.OVERWEIGHT, executive_summary="s",
        investment_thesis="Street consensus rating: Buy (28 of 35 analysts)."),
    schemas.SentimentReport: schemas.SentimentReport(
        overall_band=schemas.SentimentBand.NEUTRAL, overall_score=5.0, confidence="low", narrative="n"),
}

ARGS = {"symbol": "NVDA", "ticker": "NVDA", "curr_date": TRADE_DATE, "start_date": "2026-01-02",
        "end_date": TRADE_DATE, "indicator": "rsi", "topic": "Fed rate cut", "freq": "quarterly"}


class ScriptedModel(BaseChatModel):
    """Calls every bound tool once, then answers with TEXT."""

    structured: bool = False
    tools: tuple = ()
    calls: list = Field(default_factory=list)   # shared across bound copies
    threads: set = Field(default_factory=set)   # threads that served a tool-bound call
    fail_at: int | None = None                  # raise on this call, once

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools": tuple(tools)})

    def with_structured_output(self, schema, **kwargs):
        if not self.structured:
            raise NotImplementedError
        return RunnableLambda(lambda _: self._count() or STRUCTURED[schema])

    def _count(self) -> None:
        self.calls.append(1)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("provider unavailable")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._count()
        if self.tools:
            import threading
            import time
            self.threads.add(threading.current_thread().name)
            time.sleep(0.05)   # long enough for concurrent analysts to overlap
        if self.tools and not isinstance(messages[-1], ToolMessage):
            calls = [{"name": t.name, "id": f"call_{i}",
                      "args": {k: v for k, v in ARGS.items()
                               if k in t.tool_call_schema.model_json_schema()["properties"]}}
                     for i, t in enumerate(self.tools)]
            message = AIMessage(content="", tool_calls=calls)
        else:
            message = AIMessage(content=TEXT)
        return ChatResult(generations=[ChatGeneration(message=message)])


class _Client:
    def __init__(self, model):
        self.model = model

    def get_llm(self):
        return self.model


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Every vendor answers offline; returns the set of router methods called."""
    called: set[str] = set()
    for method, vendors in router.VENDOR_METHODS.items():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor,
                                lambda *a, _m=method, **k: called.add(_m) or f"{_m} data")
    prices = pd.DataFrame({
        "Date": pd.bdate_range(end=TRADE_DATE, periods=60),
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.5, "Volume": 1_000_000,
    })
    monkeypatch.setattr(snapshot, "load_ohlcv",
                        lambda *a, **k: called.add("ohlcv") or prices.copy())
    monkeypatch.setattr(sentiment_analyst, "fetch_stocktwits_messages", lambda *a, **k: "no posts")
    monkeypatch.setattr(sentiment_analyst, "fetch_reddit_posts", lambda *a, **k: "no posts")
    monkeypatch.setattr(yahoo_market.yf, "Ticker", lambda s: type("T", (), {"info": {"longName": "NVIDIA"}})())
    context._identity.cache_clear()
    return called


def _graph(tmp_path, monkeypatch, model, debug=False, **config):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(results_dir=str(tmp_path / "results"), data_cache_dir=str(tmp_path / "cache"),
               memory_log_path=str(tmp_path / "log.md"), **config)
    monkeypatch.setattr(trading_graph, "create_tier_client", lambda config, tier, **k: _Client(model))
    return trading_graph.TradingAgentsGraph(config=cfg, debug=debug)


@pytest.mark.unit
@pytest.mark.parametrize("structured", [False, True], ids=["free-text", "structured"])
def test_a_full_run_reaches_a_logged_decision(tmp_path, monkeypatch, offline, structured):
    graph = _graph(tmp_path, monkeypatch, ScriptedModel(structured=structured))

    state, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == state["final_rating"] == "Overweight"
    for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report",
                "investment_plan", "trader_investment_plan", "final_trade_decision"):
        assert state[key].strip(), key
    tool_methods = {"get_stock_data", "get_indicators", "get_news", "get_global_news",
                    "get_macro_indicators", "get_prediction_markets", "get_fundamentals",
                    "get_balance_sheet", "get_cashflow", "get_income_statement",
                    "get_insider_transactions", "ohlcv"}
    assert offline == tool_methods
    assert [e["rating"] for e in graph.memory_log.load_entries()] == ["Overweight"]


@pytest.mark.unit
def test_an_interrupted_run_resumes_from_its_checkpoint(tmp_path, monkeypatch, offline):
    model = ScriptedModel(fail_at=12)            # past the analysts, before the decision
    graph = _graph(tmp_path, monkeypatch, model, checkpoint_enabled=True)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        graph.propagate("NVDA", TRADE_DATE)
    calls_before = len(model.calls)

    _, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == "Overweight"
    resumed_calls = len(model.calls) - calls_before
    full_run = ScriptedModel()
    _graph(tmp_path / "fresh", monkeypatch, full_run).propagate("NVDA", TRADE_DATE)
    # The resumed run makes only the calls the interrupted one had not completed.
    assert resumed_calls == len(full_run.calls) - (model.fail_at - 1)


@pytest.mark.unit
def test_a_graph_reused_across_runs_keeps_no_run_state(tmp_path, monkeypatch, offline):
    """A backtest reuses one graph over its whole grid; holding every run's full
    state would grow without bound."""
    graph = _graph(tmp_path, monkeypatch, ScriptedModel())
    for trade_date in ("2026-01-08", TRADE_DATE):
        graph.propagate("NVDA", trade_date)

    held = [v for v in vars(graph).values() if isinstance(v, dict) and TRADE_DATE in v]
    assert held == []
    assert len(list(tmp_path.glob("results/NVDA/TradingAgentsStrategy_logs/*.json"))) == 2


@pytest.mark.unit
def test_the_analysts_run_at_the_same_time(tmp_path, monkeypatch, offline):
    model = ScriptedModel()
    graph = _graph(tmp_path, monkeypatch, model)

    assert not [n for n in graph.graph.get_graph().nodes if n.startswith("Msg Clear")]
    graph.propagate("NVDA", TRADE_DATE)

    assert len(model.threads) > 1


@pytest.mark.unit
def test_a_debug_run_prints_the_analysts_work_and_reaches_the_same_decision(tmp_path, monkeypatch, offline, capsys):
    """Debug mode streams the analysts' own graphs, so their tool calls still print."""
    graph = _graph(tmp_path, monkeypatch, ScriptedModel(), debug=True)

    state, signal = graph.propagate("NVDA", TRADE_DATE)

    assert signal == "Overweight"
    assert state["market_report"].strip() and state["fundamentals_report"].strip()
    printed = capsys.readouterr().out
    assert "get_stock_data" in printed and "get_balance_sheet" in printed


@pytest.mark.unit
def test_each_report_streams_as_soon_as_its_analyst_files_it(tmp_path, monkeypatch, offline):
    """The main state takes the analysts' reports only when the slowest one is
    done; the CLI shows each report, and stops each clock, as it lands."""
    graph = _graph(tmp_path, monkeypatch, ScriptedModel())
    reports = ("market_report", "sentiment_report", "news_report", "fundamentals_report")

    first = next(state for _, state in graph.stream_run(graph.create_run_state("NVDA", TRADE_DATE),
                                                        **graph.propagator.get_graph_args())
                 if state and any(state.get(k) for k in reports))

    assert sum(bool(first.get(k)) for k in reports) == 1


@pytest.mark.unit
def test_a_streamed_run_reads_its_own_graph_config(tmp_path, monkeypatch, offline):
    """The CLI streams the run; a process-wide config set elsewhere must not reach
    its tools, and the graph's config must not reach the caller between steps."""
    from tradingagents.dataflows.config import get_config, set_config

    graph = _graph(tmp_path, monkeypatch, ScriptedModel(), output_language="French")
    set_config({"output_language": "German"})
    seen = []
    monkeypatch.setitem(router.VENDOR_METHODS["get_stock_data"], "yfinance",
                        lambda *a, **k: seen.append(get_config()["output_language"]) or "prices")

    between = [get_config()["output_language"]
               for _ in graph.stream_run(graph.create_run_state("NVDA", TRADE_DATE), **graph.propagator.get_graph_args())]

    assert seen and set(seen) == {"French"}
    assert set(between) == {"German"}


class LoopingModel(ScriptedModel):
    """Calls a tool on every turn it is offered one (#1420)."""

    tool_turns: list = Field(default_factory=list)    # shared across bound copies
    last_turns: list = Field(default_factory=list)    # histories of the turns offered no tools

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if not self.tools:
            self.last_turns.append(messages)
            return super()._generate(messages, stop, run_manager, **kwargs)
        self.tool_turns.append(1)
        tool = self.tools[0]
        call = {"name": tool.name, "id": f"call_{len(self.tool_turns)}",
                "args": {k: v for k, v in ARGS.items()
                         if k in tool.tool_call_schema.model_json_schema()["properties"]}}
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])


@pytest.mark.unit
def test_an_analyst_that_keeps_calling_tools_writes_its_report_at_the_limit(tmp_path, monkeypatch, offline):
    """A model that does not stop calling tools must not end the run (#1420)."""
    model = LoopingModel(structured=True)
    graph = _graph(tmp_path, monkeypatch, model, max_tool_rounds=3)

    final_state, rating = graph.propagate("NVDA", TRADE_DATE)

    assert len(model.tool_turns) == 3 * 3   # three tool-using analysts, three rounds each
    for key in ("market_report", "news_report", "fundamentals_report"):
        assert final_state[key] == TEXT
    assert rating == "Overweight"


@pytest.mark.unit
def test_the_last_turn_is_offered_no_tools_and_reads_its_tool_results_as_text(tmp_path, monkeypatch, offline):
    """Offered tools, a model may call one whatever it is told; a history holding
    tool calls may be refused by a provider when no tools are bound."""
    model = LoopingModel(structured=True)
    graph = _graph(tmp_path, monkeypatch, model, max_tool_rounds=2)

    graph.propagate("NVDA", TRADE_DATE)

    wrap_ups = [h for h in model.last_turns if isinstance(h[-1], HumanMessage) and "tool round" in h[-1].content]
    assert len(wrap_ups) == 3
    for history in wrap_ups:
        assert not any(isinstance(m, ToolMessage) or getattr(m, "tool_calls", None) for m in history)
        assert any("returned]" in str(m.content) for m in history)
        assert "tool rounds are spent" in history[0].content   # the system prompt lists no tools


@pytest.mark.unit
def test_a_tool_limit_the_recursion_limit_cannot_hold_is_refused(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="max_tool_rounds"):
        _graph(tmp_path, monkeypatch, ScriptedModel(), max_tool_rounds=60, max_recur_limit=100)


class TimedModel(ScriptedModel):
    """ScriptedModel that records each call's graph step, prompt and timing."""

    seen: list = Field(default_factory=list)    # shared across bound copies

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        step = (run_manager.metadata or {}).get("langgraph_node") if run_manager else None
        started = time.monotonic()
        if step in {"Market Analyst", "agent"} or step == "Memory Log":
            time.sleep(0.2)                     # long enough to see what overlaps
        result = super()._generate(messages, stop, run_manager, **kwargs)
        prompt = "\n".join(str(m.content) for m in messages)
        self.seen.append((step, prompt, started, time.monotonic()))
        return result


@pytest.mark.unit
def test_past_decisions_settle_alongside_the_analysts(tmp_path, monkeypatch, offline):
    from tradingagents.memory import settlement

    model = TimedModel()
    graph = _graph(tmp_path, monkeypatch, model)
    graph.memory_log.store_decision("NVDA", "2025-12-31", "Rating: Buy\n\nBuy NVDA.")
    closes = pd.Series([100.0 + i for i in range(10)], index=pd.bdate_range("2026-01-02", periods=10))
    monkeypatch.setattr(settlement, "get_closes", lambda *a, **k: closes)

    graph.propagate("NVDA", TRADE_DATE)

    reflections = [c for c in model.seen if c[0] == "Memory Log"]
    assert len(reflections) == 1                # settled once, inside the run
    analyst_turns = [c for c in model.seen if c[0] == "agent"]
    assert reflections[0][2] < max(c[3] for c in analyst_turns), "settled before the analysts, not alongside"
    settled = next(e for e in graph.memory_log.load_entries() if e["date"] == "2025-12-31")
    assert not settled["pending"]
    lessons = graph.memory_log.get_past_context("NVDA", as_of=TRADE_DATE)
    assert lessons
    pm_prompt = next(c[1] for c in model.seen if c[0] == "Portfolio Manager")
    assert lessons in pm_prompt


@pytest.mark.unit
def test_a_settlement_failure_is_noted_and_the_run_goes_on(tmp_path, monkeypatch, offline):
    """The analysts have spent their tokens by the time the join waits on settlement."""
    from tradingagents.reporting import write_report_tree

    graph = _graph(tmp_path, monkeypatch, ScriptedModel(structured=True))

    def locked():
        raise OSError("memory log is locked")

    monkeypatch.setattr(graph, "settle_all_pending", locked)
    final_state, rating = graph.propagate("NVDA", TRADE_DATE)

    assert rating == "Overweight"
    assert "could not be settled" in final_state["memory_note"]
    report = write_report_tree(final_state, "NVDA", tmp_path / "report").read_text()
    assert "Memory log: Past decisions could not be settled" in report


@pytest.mark.unit
def test_the_run_settles_other_tickers_due_decisions_too(tmp_path, monkeypatch, offline):
    """A ticker a scheduler stopped analysing still gets its decisions settled (#1445)."""
    from tradingagents.memory import settlement

    graph = _graph(tmp_path, monkeypatch, ScriptedModel(structured=True))
    graph.memory_log.store_decision("MSFT", "2026-01-02", "Rating: Buy\n\nBuy MSFT.")
    closes = pd.Series([100.0 + i for i in range(10)], index=pd.bdate_range("2026-01-02", periods=10))
    monkeypatch.setattr(settlement, "get_closes", lambda *a, **k: closes)

    graph.propagate("NVDA", TRADE_DATE)

    msft = next(e for e in graph.memory_log.load_entries() if e["ticker"] == "MSFT")
    assert not msft["pending"]


@pytest.mark.unit
def test_the_memory_step_reads_lessons_as_of_the_trade_date_and_settles_once(tmp_path, monkeypatch, offline):
    """A past-dated run reads only lessons known by its date (#1251); a resumed run
    that re-runs the step settles nothing twice."""
    from tradingagents.memory import settlement

    graph = _graph(tmp_path, monkeypatch, ScriptedModel(structured=True))
    graph.memory_log.store_decision("NVDA", "2025-12-31", "Rating: Buy\n\nBuy NVDA.")
    closes = pd.Series([100.0 + i for i in range(10)], index=pd.bdate_range("2026-01-02", periods=10))
    monkeypatch.setattr(settlement, "get_closes", lambda *a, **k: closes)
    asked = []
    real = graph.memory_log.get_past_context
    monkeypatch.setattr(graph.memory_log, "get_past_context",
                        lambda ticker, as_of=None, **k: asked.append(as_of) or real(ticker, as_of=as_of, **k))
    state = {"company_of_interest": "NVDA", "trade_date": "2026-01-20"}

    graph._memory_step(state)
    log_after_first = (tmp_path / "log.md").read_text()
    graph._memory_step(state)

    assert asked == ["2026-01-20", "2026-01-20"]
    assert (tmp_path / "log.md").read_text() == log_after_first


def test_research_contract_survives_graph_and_controls_settlement(tmp_path, monkeypatch, offline):
    mandate = {
        "ticker": "NVDA", "analysis_date": TRADE_DATE,
        "prediction_horizon_trading_days": 20, "benchmark": "QQQ",
        "quote_currency": "USD", "valid_until": "2026-02-10",
    }
    graph = _graph(tmp_path, monkeypatch, ScriptedModel(structured=True),
                   research_mandate=mandate)
    assert graph.config["holding_period_days"] == 20
    assert graph.config["benchmark_ticker"] == "QQQ"
    state, rating = graph.propagate("NVDA", TRADE_DATE)
    assert state["research_mandate"]["prediction_horizon_trading_days"] == 20
    assert rating == "Overweight"
    graph.save_reports(state, "NVDA", tmp_path / "report")
    assert "benchmark QQQ" in (tmp_path / "report/complete_report.md").read_text()
    with pytest.raises(ValueError, match="do not match"):
        graph.propagate("NVDA", "2026-01-08")


def test_managed_runs_capture_all_consumed_sources_and_isolate_experiments(tmp_path, monkeypatch, offline):
    import json

    from tradingagents.application.runs import RunScope, execute_research
    from tradingagents.domain.research import ResearchMandate
    from tradingagents.infrastructure.artifacts import read_verified
    from tradingagents.infrastructure.evidence import verify_bundle

    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: _Client(ScriptedModel(structured=True)))
    mandate = ResearchMandate(ticker="NVDA", analysis_date=TRADE_DATE,
                              prediction_horizon_trading_days=20, benchmark="QQQ",
                              quote_currency="USD", valid_until="2026-02-10")
    outputs = [execute_research(tmp_path, RunScope("internal", experiment, "task", "attempt1"),
                                mandate, DEFAULT_CONFIG) for experiment in ("control", "candidate")]
    assert outputs[0].path != outputs[1].path
    for result in outputs:
        run = json.loads(read_verified(result.path / "run.json", result.manifest_sha256))
        assert run["rating"] == "Overweight"
        evidence = verify_bundle(result.path / "evidence", result.evidence_sha256)
        methods = {r["method"] for r in evidence["records"]}
        assert set(router.VENDOR_METHODS) <= methods
        assert {"get_verified_market_snapshot", "instrument_context", "past_context",
                "sentiment_prompt_input"} <= methods
        assert (result.path / "memory/decisions.md").read_text().count("ENTRY_END") == 1
        for file, ref in run["files"].items():
            read_verified(result.path / file, ref)
    with pytest.raises(FileExistsError):
        execute_research(tmp_path, RunScope("internal", "control", "task", "attempt1"),
                         mandate, DEFAULT_CONFIG)


def test_real_graph_output_has_quality_checks_and_requires_fixed_version_review(tmp_path, monkeypatch, offline):
    import json

    from tradingagents.application.runs import RunScope, execute_research
    from tradingagents.domain.research import ResearchMandate
    from tradingagents.infrastructure.reports import ReportStore

    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: _Client(ScriptedModel(structured=True)))
    cfg = {**DEFAULT_CONFIG, "research_policy": {"approved_tickers": ["NVDA"]},
           "source_licenses": dict.fromkeys(
               ("yfinance", "sec_edgar", "stocktwits", "reddit", "fred", "polymarket"), "fixture-approved")}
    mandate = ResearchMandate(ticker="NVDA", analysis_date=TRADE_DATE,
                              prediction_horizon_trading_days=20, benchmark="QQQ",
                              quote_currency="USD", valid_until="2099-01-01")
    result = execute_research(tmp_path, RunScope("internal", "test", "task", "attempt"),
                              mandate, cfg)
    quality = json.loads((result.path / "quality.json").read_bytes())
    assert quality["status"] == "needs_review"
    assert quality["calculations"][0]["close"] == "100.5"
    assert "unverified_currency" in {i["code"] for i in quality["issues"]}
    assert "blocked" not in (result.path / "report/quality.md").read_text()
    manifest = json.loads((result.path / "run.json").read_bytes())
    assert manifest["implementation"]["sources"]["agents/schemas.py"]
    store = ReportStore(tmp_path / "reports.db")
    report = store.register(result.path, result.manifest_sha256, "analyst")
    assert store.get(report)["status"] == "draft"
    store.transition(report, "approved", "reviewer", "Fixture review only, not financial validation",
                     acknowledgements=[i["code"] for i in quality["issues"]])
    assert store.transition(report, "published", "publisher", "Local fixture release")["status"] == "published"


@pytest.mark.parametrize("terminal", ["complete", "cancel", "budget"])
def test_managed_task_accepts_only_active_budgeted_real_graph_result(
    tmp_path, monkeypatch, offline, terminal,
):
    from tradingagents.application.runs import RunScope, execute_research
    from tradingagents.application.worker import BudgetCallback
    from tradingagents.domain.tasks import TaskInput
    from tradingagents.infrastructure.tasks import BudgetExceeded, LeaseLost, TaskStore

    models = []

    def factory(config, tier, **kwargs):
        assert kwargs["callbacks"]
        assert config["llm_max_retries"] == 0 and config["max_tokens"] == 4096
        model = ScriptedModel(callbacks=kwargs["callbacks"])
        models.append(model)
        return _Client(model)

    monkeypatch.setattr(trading_graph, "create_tier_client", factory)
    payload = TaskInput.model_validate({
        "workspace": "internal", "experiment": "test", "config": DEFAULT_CONFIG,
        "mandate": {"ticker": "NVDA", "analysis_date": TRADE_DATE,
                    "prediction_horizon_trading_days": 5, "benchmark": "SPY",
                    "quote_currency": "USD", "valid_until": "2099-01-01"},
        "limits": {"budget_microusd": 100_000_000},
    })
    store = TaskStore(tmp_path / "tasks.db")
    task = store.submit(payload, "analyst", "same")
    row = store.claim("worker")
    result = execute_research(
        tmp_path, RunScope("internal", "test", task, row["attempt"]),
        payload.mandate, row["payload"]["config"],
        callbacks=[BudgetCallback(store, task, row["attempt"])],
        expected_implementation=row["implementation"],
    )
    ledger = store.get(task)["calls"]
    assert len(ledger) == sum(len(m.calls) for m in models) > 0
    assert all(c["actual_microusd"] is None for c in ledger)
    if terminal == "cancel":
        store.cancel(task, "operator")
        with pytest.raises(LeaseLost):
            store.complete(task, row["attempt"], result.path, result.manifest_sha256)
    elif terminal == "budget":
        # Exhaust a bounded task after a graph returns; even swallowed callback
        # errors cannot permit acceptance.
        with pytest.raises(BudgetExceeded):
            for i in range(1000):
                store.reserve_call(task, row["attempt"], f"extra-{i}", "test")
        with pytest.raises(BudgetExceeded):
            store.complete(task, row["attempt"], result.path, result.manifest_sha256)
    else:
        store.complete(task, row["attempt"], result.path, result.manifest_sha256)
        assert store.get(task)["manifest_hash"] == result.manifest_sha256
        with pytest.raises(LeaseLost):
            store.complete(task, row["attempt"], result.path, result.manifest_sha256)
        assert sum(e["action"] == "succeeded" for e in store.get(task)["events"]) == 1


def test_real_graph_service_review_evaluation_and_restore_closed_loop(tmp_path, monkeypatch, offline):
    from tradingagents.application.runs import RunScope, execute_research
    from tradingagents.application.service import ResearchService
    from tradingagents.application.worker import BudgetCallback
    from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
    from tradingagents.domain.service import ReviewRequest, SubmitRequest
    from tradingagents.infrastructure.identity import SCOPES
    from tradingagents.infrastructure.recovery import backup, restore

    service = ResearchService(tmp_path / "db", tmp_path / "artifacts", {
        "internal": {"daily": {"config": {
            "research_policy": {"approved_tickers": ["NVDA"]},
            "source_licenses": dict.fromkeys(
                ("yfinance", "sec_edgar", "stocktwits", "reddit", "fred", "polymarket"), "fixture"),
        }, "limits": {"budget_microusd": 100_000_000}, "workspace_budget_microusd": 300_000_000}},
    })
    _, token = service.identities.issue("analyst", "internal", SCOPES)
    _, reviewer_token = service.identities.issue("reviewer", "internal", SCOPES)
    analyst, reviewer = (service.identities.authenticate(t) for t in (token, reviewer_token))
    mandate = {"ticker": "NVDA", "analysis_date": TRADE_DATE, "benchmark": "SPY",
               "prediction_horizon_trading_days": 5, "quote_currency": "USD", "valid_until": "2099-01-01"}
    sessions = ["2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-20"]
    plan = service.plan_experiment(analyst, ExperimentPlan.model_validate({
        "workspace": "internal", "experiment": "closed-loop", "mode": "diagnostic",
        "price_basis": "unadjusted_close", "calendar_source": "offline fixture",
        "calendar_evidence": "Explicit synthetic sessions; no historical-model knowledge certification",
        "samples": [{"key": k, "mandate": mandate, "sessions": sessions} for k in ("sample", "absent")],
    }))
    task = service.submit(analyst, SubmitRequest.model_validate({
        "workspace": "internal", "experiment": "closed-loop", "template": "daily", "mandate": mandate,
    }), "sample")["id"]
    row = service.tasks.claim("offline-runner")
    monkeypatch.setattr(trading_graph, "create_tier_client",
                        lambda config, tier, **k: _Client(ScriptedModel(callbacks=k["callbacks"])))
    payload = row["payload"]
    result = execute_research(
        service.root, RunScope("internal", "closed-loop", task, row["attempt"]),
        payload["mandate"], payload["config"],
        callbacks=[BudgetCallback(service.tasks, task, row["attempt"])],
        expected_implementation=row["implementation"],
    )
    service.tasks.complete(task, row["attempt"], result.path, result.manifest_sha256)
    report = service.register(analyst, task)["id"]
    quality = service.report(reviewer, report)["quality"]
    service.review(reviewer, report, ReviewRequest(
        action="approved", reason="Offline full graph review; not a financial effectiveness claim",
        acknowledgements=tuple(i["code"] for i in quality["issues"]),
    ))
    service.review(reviewer, report, ReviewRequest(action="published", reason="Local fixture release"))
    prediction = service.register_prediction(analyst, plan["id"], task, report)
    observation = service.observe(analyst, prediction["id"], ObservationInput.model_validate({
        "entry_session": sessions[0], "exit_session": sessions[-1],
        "asset": {"symbol": "NVDA", "currency": "USD", "basis": "unadjusted_close",
                  "entry": "100.5", "exit": "110.55"},
        "benchmark": {"symbol": "SPY", "currency": "USD", "basis": "unadjusted_close",
                      "entry": "200", "exit": "210"},
        "source": "offline prices", "source_payload": "Synthetic retained prices; USD",
    }))
    assert observation["result"]["excess_return"] == "0.05"
    assert prediction["manifest_sha256"] == result.manifest_sha256
    summary = service.experiment(analyst, plan["id"])
    assert summary["planned_total"] == 2 and summary["final_samples"] == summary["pending_samples"] == 1
    assert summary["rating_counts"] == {"Overweight": 1}
    ref = backup(service.tasks.path, service.root, tmp_path / "backup")
    restored_path = restore(tmp_path / "backup", ref, tmp_path / "restored")
    restored = ResearchService(restored_path, tmp_path / "restored/artifacts", {})
    _, new_token = restored.identities.issue("analyst", "internal", SCOPES)
    assert restored.experiment(restored.identities.authenticate(new_token), plan["id"]) == summary
    assert restored.tasks.get(task)["calls"] and service.operations(analyst)["unknown_cost_calls"] > 0
