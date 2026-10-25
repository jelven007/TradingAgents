"""Isolated browser demos: actual graph execution and lifecycle, synthetic inputs only."""

from __future__ import annotations

import os
import secrets
import socket
import threading
import time
import uuid
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, START, StateGraph

from tradingagents.application.execution import LocalExecution
from tradingagents.application.runs import RunScope, execute_research
from tradingagents.application.service import ResearchService
from tradingagents.application.worker import BudgetCallback, run_one
from tradingagents.domain.evaluation import ExperimentPlan
from tradingagents.domain.service import SubmitRequest
from tradingagents.domain.tasks import TaskInput
from tradingagents.infrastructure.artifacts import digest
from tradingagents.infrastructure.browser_accounts import ROLE_SCOPES, SESSION_SECONDS
from tradingagents.infrastructure.evaluations import template_fingerprint
from tradingagents.infrastructure.evidence import record_evidence
from tradingagents.infrastructure.identity import AuthenticationError, Principal
from tradingagents.infrastructure.reports import database
from tradingagents.infrastructure.tasks import BudgetExceeded, LeaseLost, TaskStore
from tradingagents.reporting import write_report_tree

NOTICE = "合成演示：行情、新闻、财务和评级均为预设内容；实际执行流程并保存记录，不调用付费模型。"
TEXTS = (
    ("Market Analyst", "market_report", "合成行情：开盘98、最高101、最低97、收盘100 USD，成交量100万。示例趋势上行。"),
    ("Social Analyst", "sentiment_report", "合成讨论：60条正向、25条中性、15条负向。这些讨论不存在于真实社交网站。"),
    ("News Analyst", "news_report", "合成事件：虚构新产品计划及行业竞争讨论。未引用真实公告或媒体，首次公开时间未知。"),
    ("Fundamentals Analyst", "fundamentals_report", "合成经营假设：收入增长20%、经营利润率25%。这些数值不是NVDA财报事实。"),
    ("Research Manager", "investment_plan", "多方假设趋势与经营改善；空方指出所有输入均为合成资料，不能支持真实投资判断。"),
    ("Trader", "trader_investment_plan", "仅展示研究方案：与SPY在相同窗口、USD和未复权收盘价下观察。不安排交易或资金配置。"),
    ("Portfolio Manager", "final_trade_decision", "**Rating**: Overweight\n\n预设增持评级仅用于体验流程。合成数据无法证明真实业绩。\n\n核验输入来源、研究期限和失效条件后，由复核员批准。"),
)


def templates():
    return {"demo": {"synthetic-demo": {
        "config": {"llm_provider": "openai_compatible", "quick_think_provider": None,
                   "deep_think_provider": None, "quick_think_llm": "synthetic-script",
                   "deep_think_llm": "synthetic-script", "demo_mode": True,
                   "research_policy": {"approved_tickers": ["NVDA", "AAPL", "MSFT", "SPY"],
                                       "allow_listed_stocks": True},
                   "source_licenses": {"demo": "synthetic-local-only"}},
        "limits": {"max_calls": 10, "max_seconds": 90, "max_attempts": 1,
                   "budget_microusd": 10000, "reserve_per_call_microusd": 1000},
        "workspace_budget_microusd": 1000000,
    }}}


class DemoGraph:
    def __init__(self, config, selected_analysts, callbacks):
        self.config, self.analysts = config, list(selected_analysts)
        graph = StateGraph(dict)
        previous = START
        for index, (stage, field, text) in enumerate(TEXTS):
            if index < 4 and ("market", "social", "news", "fundamentals")[index] not in self.analysts:
                continue
            mandate = config["research_mandate"]
            text = text.replace("NVDA", mandate["ticker"]).replace("SPY", mandate["benchmark"])
            text = text.replace("USD", mandate["quote_currency"])
            model = FakeListChatModel(responses=[f"{NOTICE}\n\n{text}"], callbacks=callbacks)

            def node(state, config, *, field=field, model=model):
                message = model.invoke("返回本阶段的合成研究文本", config=config)
                time.sleep(0.35)
                return {**state, field: message.content}

            graph.add_node(stage, node)
            graph.add_edge(previous, stage)
            previous = stage
        graph.add_edge(previous, END)
        self.graph = graph.compile()
        self.callbacks = callbacks

    def propagate(self, ticker, trade_date, **kwargs):
        record_evidence("demo", "verified_market_facts", {}, {
            "ticker": ticker, "as_of_date": trade_date, "price_date": trade_date,
            "currency": self.config["research_mandate"]["quote_currency"], "synthetic": True,
            "values": {"Open": "98", "High": "101", "Low": "97", "Close": "100",
                       "Volume": "1000000"},
        })
        record_evidence("demo", "synthetic_context", {}, {"notice": NOTICE})
        mandate = self.config["research_mandate"]
        state = self.graph.invoke({
            "company_of_interest": ticker, "trade_date": trade_date, "research_mandate": mandate,
            "final_rating": "Overweight", "memory_note": NOTICE,
            "instrument_context": f"{ticker} · 合成演示",
        }, config={"callbacks": self.callbacks})
        state["final_trade_decision"] += (
            f"\n\n研究日：{trade_date}；期限：{mandate['prediction_horizon_trading_days']}个会话；"
            f"基准：{mandate['benchmark']}；币种：{mandate['quote_currency']}。"
        )
        return state, "Overweight"

    def run_settings(self):
        return {"demo_mode": True, "notice": NOTICE, "external_requests": 0,
                "llm_provider": "synthetic-script", "analysts": self.analysts}

    def save_reports(self, state, ticker, path):
        write_report_tree(state, ticker, path, settings=self.run_settings())


def demo_child(db_path, root, task_id, attempt):
    def refuse(*args, **kwargs):
        raise RuntimeError("demo network access is disabled")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    store, stop = TaskStore(Path(db_path)), threading.Event()

    def watchdog():
        while not stop.wait(0.5):
            try:
                store.check_lease(task_id, attempt)
            except Exception:
                os._exit(75)

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        row = store.get(task_id)
        payload = TaskInput.model_validate(row["payload"])
        if payload.workspace != "demo" or payload.config.get("demo_mode") is not True:
            raise ValueError("synthetic task required")
        result = execute_research(
            Path(root), RunScope(payload.workspace, payload.experiment, task_id, attempt),
            payload.mandate, payload.config, selected_analysts=payload.selected_analysts,
            portfolio=payload.portfolio, callbacks=[BudgetCallback(store, task_id, attempt)],
            allocation_valuation=payload.allocation_valuation,
            graph_factory=DemoGraph, expected_implementation=row["implementation"],
        )
        store.complete(task_id, attempt, result.path, result.manifest_sha256)
    except Exception as exc:
        with suppress(LeaseLost):
            store.fail(task_id, attempt, type(exc).__name__)
    finally:
        stop.set()


class DemoExecution(LocalExecution):
    def _run(self, task_id):
        try:
            run_one(self.store, self.root, "demo-worker", task_id=task_id,
                    max_concurrency=self.max_concurrency, process_target=demo_child)
        finally:
            with self.lock:
                self.active.discard(task_id)


class DemoService(ResearchService):
    def __init__(self, root):
        root = Path(root)
        super().__init__(root / "store.sqlite", root / "artifacts", templates())
        self.execution = DemoExecution(self.tasks, self.root)

    def _execution_status(self, config):
        return {"credentials_present": True, "missing_providers": [],
                "provider_connectivity_verified": False, "mode": "synthetic_demo"}

    def session(self, principal):
        return {**super().session(principal), "demo_mode": True, "demo_notice": NOTICE,
                "demo_analysis_date": "2026-10-09"}

    def settings(self, principal):
        raise PermissionError("demo model settings are fixed")

    def save_settings(self, principal, data):
        raise PermissionError("demo model settings are fixed")

    def test_settings(self, principal, data):
        raise PermissionError("demo model settings are fixed")

    def research(self, principal, request, idem_key):
        request = SubmitRequest.model_validate(request)
        for scope in ("task:create", "task:execute", "report:register", "evaluation:write"):
            self.authorize(principal, request.workspace, scope)
        mandate = request.mandate
        _, payload = self._prepare(request)
        with database(self.tasks.path) as db:
            planned = db.execute("SELECT 1 FROM experiments WHERE workspace=? AND name=?",
                                 ("demo", request.experiment)).fetchone()
        if planned:
            return super().research(principal, request, idem_key)
        sessions, current = [], date.fromisoformat(mandate.analysis_date)
        while len(sessions) < mandate.prediction_horizon_trading_days + 1:
            current += timedelta(days=1)
            if current.weekday() < 5:
                sessions.append(current.isoformat())
        plan = ExperimentPlan.model_validate({
            "workspace": "demo", "experiment": request.experiment, "mode": "diagnostic",
            "price_basis": "unadjusted_close", "calendar_source": "合成工作日序列",
            "calendar_evidence": "本机合成日期，仅用于流程演示，不是核定的交易所日历。",
            "samples": [{"key": idem_key, "template": request.template,
                         "mandate": mandate, "sessions": sessions}],
        })
        result = self.evaluations.create(plan, principal.subject, {
            idem_key: template_fingerprint(
                payload.config, payload.selected_analysts, payload.limits.model_dump(mode="json"),
            ),
        })
        self.identities.audit(principal, "evaluation:plan", result["id"])
        return super().research(principal, request, idem_key)

    def experiment(self, principal, experiment_id):
        result = super().experiment(principal, experiment_id)
        sample = result["experiment"]["plan"]["samples"][0]
        result["demo_observation"] = {
            "exit_session": sample["sessions"][-1],
            "asset": {"entry": "100", "exit": "108"},
            "benchmark": {"entry": "200", "exit": "206"},
            "source": "本机合成价格", "source_payload": (
                f"合成{sample['mandate']['ticker']}100→108、"
                f"{sample['mandate']['benchmark']}200→206，"
                f"{sample['mandate']['quote_currency']}，未复权收盘价。"
            ),
        }
        return result


class DemoSessions:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "sessions.sqlite"
        self.lock, self.services = threading.Lock(), {}
        with database(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS demo_sessions (
                token_hash TEXT PRIMARY KEY, id TEXT NOT NULL, role TEXT NOT NULL,
                csrf TEXT NOT NULL, expires REAL NOT NULL)""")
        self.path.chmod(0o600)

    def create(self):
        token, session_id = secrets.token_urlsafe(32), uuid.uuid4().hex
        with database(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM demo_sessions WHERE expires>?",
                          (time.time(),)).fetchone()[0] >= 64:
                raise BudgetExceeded("demo session capacity reached")
            db.execute("INSERT INTO demo_sessions VALUES (?,?,?,?,?)",
                       (digest(token.encode()), session_id, "researcher", secrets.token_urlsafe(32),
                        time.time() + SESSION_SECONDS))
        return token

    def authenticate(self, token):
        with database(self.path) as db:
            row = db.execute("SELECT * FROM demo_sessions WHERE token_hash=?",
                             (digest(token.encode()),)).fetchone()
        if not row or row["expires"] <= time.time():
            raise AuthenticationError("demo session expired")
        with self.lock:
            if row["id"] not in self.services:
                if len(self.services) >= 64:
                    raise BudgetExceeded("demo service capacity reached")
                self.services[row["id"]] = DemoService(self.root / row["id"])
            service = self.services[row["id"]]
        scopes = ROLE_SCOPES[row["role"]]
        if row["role"] == "researcher":
            scopes = scopes | {"settings:read", "settings:write"}
        principal = Principal(f"demo-{row['role']}", "demo", frozenset(scopes))
        return service, principal, {"username": principal.subject, "role": row["role"],
                                    "csrf": row["csrf"]}

    def switch(self, token, role):
        if role not in {"researcher", "reviewer", "operator"}:
            raise ValueError("unknown demo role")
        with database(self.path) as db:
            db.execute("UPDATE demo_sessions SET role=?,csrf=? WHERE token_hash=?",
                       (role, secrets.token_urlsafe(32), digest(token.encode())))

    def logout(self, token):
        with database(self.path) as db:
            db.execute("DELETE FROM demo_sessions WHERE token_hash=?", (digest(token.encode()),))

    def close(self):
        for service in self.services.values():
            service.execution.close()
