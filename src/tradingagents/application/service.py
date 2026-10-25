"""Scoped research facade shared by the local HTTP and CLI interfaces."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from tradingagents.application.execution import LocalExecution, execution_status
from tradingagents.application.investor import WatchlistInput, instrument, report_brief
from tradingagents.application.model_probe import probe_model
from tradingagents.application.securities import catalog, search, security
from tradingagents.application.worker import finalize_report
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput
from tradingagents.domain.model_settings import (
    PROVIDERS,
    ModelProbeInput,
    ModelSettingsInput,
    default_endpoint,
)
from tradingagents.domain.quality import ResearchPolicy
from tradingagents.domain.research_settings import (
    ANALYSTS,
    ASSETS,
    BENCHMARKS,
    CURRENCIES,
    PURPOSES,
    InputError,
    ResearchProfile,
    ResearchSettingsInput,
)
from tradingagents.domain.service import CostRequest, ResearchTemplate, ReviewRequest, SubmitRequest
from tradingagents.domain.tasks import TaskInput, TaskLimits
from tradingagents.infrastructure.artifacts import component
from tradingagents.infrastructure.browser_accounts import AccountInput, BrowserAccounts
from tradingagents.infrastructure.evaluations import EvaluationStore, template_fingerprint
from tradingagents.infrastructure.identity import IdentityStore, Principal
from tradingagents.infrastructure.model_settings import ModelSettingsStore
from tradingagents.infrastructure.reports import ReportStore, database, verify_run
from tradingagents.infrastructure.research_settings import ResearchSettingsStore
from tradingagents.infrastructure.tasks import STAGES, BudgetExceeded, TaskStore
from tradingagents.infrastructure.watchlist import WatchlistStore


class ResearchService:
    def __init__(self, db_path: Path, root: Path, templates: dict):
        self.root = Path(root).resolve()
        if not self.root.exists():
            self.root.mkdir(parents=True, mode=0o700)
        self.tasks = TaskStore(db_path)
        self.reports = ReportStore(db_path)
        self.identities = IdentityStore(db_path)
        self.accounts = BrowserAccounts(db_path)
        self.evaluations = EvaluationStore(db_path)
        self.model_settings = ModelSettingsStore(db_path)
        self.research_settings = ResearchSettingsStore(db_path)
        self.watchlists = WatchlistStore(db_path)
        self.probe_slots = threading.BoundedSemaphore(2)
        self.execution = LocalExecution(self.tasks, self.root)
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
            completed = db.execute(
                """SELECT t.id FROM tasks t WHERE status='succeeded' AND result_path IS NOT NULL
                AND EXISTS (SELECT 1 FROM task_events e WHERE e.task_id=t.id
                            AND e.action='auto_report_requested')
                AND NOT EXISTS (SELECT 1 FROM task_events e WHERE e.task_id=t.id
                                AND e.action='report_registered')""",
            ).fetchall()
        for row in completed:
            finalize_report(self.tasks, self.root, row["id"])

    def _execution_status(self, config):
        return execution_status(config, self.tasks.path)

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

    def _template(self, workspace, name, entry=None):
        entry = entry or self._profiles(workspace).get(name)
        if entry is None:
            raise InputError("template", "研究模板不存在，请重新选择。")
        profile = entry["profile"]
        template = self.templates[workspace][entry["base_template"]]
        config = deepcopy(template.config)
        # Baseline policy and licenses remain operator-owned.
        config["research_policy"] = {
            **config.get("research_policy", {}), "approved_tickers": list(profile.tickers),
        }
        if entry["version"]:
            config["research_settings_revision"] = entry["id"]
        return template.model_copy(update={
            "config": self.model_settings.effective(workspace, config),
            "analysts": profile.analysts, "limits": profile.limits,
            "max_pending": profile.max_pending,
            "workspace_budget_microusd": profile.workspace_budget_microusd,
        })

    def _profiles(self, workspace):
        result = {}
        for name, template in self.templates.get(workspace, {}).items():
            tickers = ResearchPolicy.model_validate(
                template.config.get("research_policy", {}),
            ).approved_tickers
            profile = ResearchProfile.model_validate({
                "name": name, "title": name, "tickers": tickers,
                "defaults": {"ticker": tickers[0] if tickers else ""},
                "analysts": template.analysts, "limits": template.limits,
                "max_pending": template.max_pending,
                "workspace_budget_microusd": template.workspace_budget_microusd,
            })
            result[name] = {"profile": profile, "version": 0, "base_template": name}
        result.update(self.research_settings.active(workspace))
        return result

    def research_profiles(self, principal):
        self.authorize(principal, principal.workspace, "settings:read")
        result = {"templates": [
            {**entry["profile"].model_dump(mode="json"), "version": entry["version"],
             "source": "配置" if entry["version"] else "预置"}
            for entry in self._profiles(principal.workspace).values()
        ], "options": {"analysts": ANALYSTS, "asset_types": ASSETS,
                       "purposes": PURPOSES, "currencies": CURRENCIES,
                       "benchmarks": BENCHMARKS}}
        self.identities.audit(principal, "settings:research:read")
        return result

    def save_research_profile(self, principal, data: ResearchSettingsInput):
        self.authorize(principal, principal.workspace, "settings:write")
        data = ResearchSettingsInput.model_validate(data)
        entries = self._profiles(principal.workspace)
        existing = entries.get(data.profile.name)
        source = entries.get(data.base_template or "", existing)
        if source is None:
            raise InputError("base_template", "请选择已存在的基础模板。")
        base = existing["base_template"] if existing else source["base_template"]
        result = self.research_settings.save(principal.workspace, data, principal.subject, base)
        self.identities.audit(principal, "settings:research:write", data.profile.name)
        return result

    def settings(self, principal: Principal) -> dict:
        self.authorize(principal, principal.workspace, "settings:read")
        baseline = next(iter(self.templates.get(principal.workspace, {}).values()), None)
        result = self.model_settings.public(
            principal.workspace, baseline.config if baseline else DEFAULT_CONFIG,
        )
        result["providers"] = [
            {"id": provider, "default_url": default_endpoint(provider)} for provider in PROVIDERS
        ]
        self.identities.audit(principal, "settings:read")
        return result

    def list_accounts(self, principal: Principal):
        self.authorize(principal, principal.workspace, "accounts:manage")
        self.identities.audit(principal, "accounts:list")
        return self.accounts.list(principal.workspace)

    def create_account(self, principal: Principal, data: AccountInput):
        self.authorize(principal, principal.workspace, "accounts:manage")
        result = self.accounts.create(principal.workspace, data)
        self.identities.audit(principal, "accounts:create", result["id"])
        return result

    def save_settings(self, principal: Principal, data: ModelSettingsInput) -> dict:
        self.authorize(principal, principal.workspace, "settings:write")
        data = ModelSettingsInput.model_validate(data)
        self.model_settings.save(principal.workspace, data, principal.subject)
        self.identities.audit(principal, "settings:write", str(data.expected_version + 1))
        # Write-only identities receive no configuration details.
        return {"version": data.expected_version + 1}

    def test_settings(self, principal: Principal, data: ModelProbeInput) -> dict:
        self.authorize(principal, principal.workspace, "settings:write")
        data = ModelProbeInput.model_validate(data)
        if not self.probe_slots.acquire(blocking=False):
            raise BudgetExceeded("model connection test capacity reached")
        try:
            record, key = self.model_settings.probe_draft(principal.workspace, data)
            result = probe_model(record, key, data.tier)
            self.identities.audit(principal, "settings:test", data.tier,
                                  outcome=result["category"])
            return result
        finally:
            self.probe_slots.release()

    def _prepare(self, request):
        entry = self._profiles(request.workspace).get(request.template)
        template = self._template(request.workspace, request.template, entry)
        profile = entry["profile"]
        listed = security(request.mandate.ticker) if request.mandate.asset_type == "stock" else None
        policy = template.config["research_policy"]
        if request.mandate.ticker not in profile.tickers and not (
            policy.get("allow_listed_stocks") and listed
        ):
            raise InputError("mandate.ticker", "标的未在模板批准清单中，请先配置研究模板。")
        if request.mandate.asset_type not in profile.asset_types:
            raise InputError("mandate.asset_type", "模板不允许该资产类型。")
        if request.mandate.purpose not in profile.purposes:
            raise InputError("mandate.purpose", "模板不允许该研究用途。")
        if request.mandate.analysis_date > datetime.now(UTC).date().isoformat():
            raise InputError("mandate.analysis_date", "研究日期不能晚于今天。")
        analysts, limits = template.analysts, template.limits
        if request.options:
            if request.options.selected_analysts is not None:
                analysts = request.options.selected_analysts
            if not analysts or len(set(analysts)) != len(analysts) or not set(analysts) <= set(template.analysts):
                raise InputError("options.selected_analysts", "至少选择一个模板允许的分析师，且不能重复。")
            reductions = request.options.model_dump(exclude_none=True, exclude={
                "selected_analysts", "execution_mode", "display_currency", "stock_question",
            })
            for key, value in reductions.items():
                if value > getattr(template.limits, key):
                    raise InputError(f"options.{key}", "超过模板上限，请降低数值或先修改模板配置。")
            limits = TaskLimits.model_validate({**limits.model_dump(), **reductions})
        if limits.budget_microusd < limits.reserve_per_call_microusd:
            raise InputError("options.budget_microusd", "预算不能低于一次调用预留额。")
        config = deepcopy(template.config)
        if request.options and request.options.execution_mode == "guided_stock":
            if request.mandate.asset_type != "stock" or request.mandate.purpose == "portfolio_review":
                raise InputError("options.execution_mode", "股票快捷研究用于一般或事件研究；账户复核请选择完整流程。")
            if listed and request.mandate.quote_currency != listed["quote_currency"]:
                raise InputError("mandate.quote_currency", "报价币种由股票资料确定；人民币/美元换算请使用显示币种。")
            if limits.max_calls < 8 or limits.budget_microusd < 8 * limits.reserve_per_call_microusd:
                raise InputError("options.budget_microusd", "默认路线需容纳最多8次调用（含重试）；请恢复模板默认限额。")
            config.update({
                "execution_mode": "guided_stock",
                "display_currency": request.options.display_currency,
                "stock_question": request.options.stock_question,
                "selected_security": listed,
            })
        # Freeze only the authorized selection; a local catalog cannot grant scope.
        config["research_policy"]["approved_tickers"] = list(dict.fromkeys(
            [*config["research_policy"]["approved_tickers"], request.mandate.ticker],
        ))
        if request.portfolio is not None and request.portfolio.currency != request.mandate.quote_currency:
            raise InputError("portfolio.currency", "持仓币种必须与研究报价币种一致。")
        value = request.allocation_valuation
        if request.mandate.purpose == "portfolio_review" and (request.portfolio is None or value is None):
            raise InputError("allocation_valuation", "持仓复核需要明确的持仓上下文和账户估值。")
        if value is not None:
            if request.mandate.purpose != "portfolio_review":
                raise InputError("mandate.purpose", "账户估值只适用于持仓复核。")
            if (value.ticker != request.mandate.ticker or value.currency != request.mandate.quote_currency
                    or value.valuation_date != request.mandate.analysis_date):
                raise InputError("allocation_valuation.valuation_date", "估值标的、币种和日期须与本次研究一致。")
            position = request.portfolio.position_in(value.ticker) if request.portfolio else None
            if value.current_units != Decimal(str(position.quantity if position else 0)):
                raise InputError("allocation_valuation.current_units", "当前数量必须与本次持仓表一致。")
        payload = TaskInput.model_validate({
            "workspace": request.workspace, "experiment": request.experiment,
            "mandate": request.mandate, "config": config,
            "selected_analysts": analysts, "portfolio": request.portfolio,
            "allocation_valuation": value, "limits": limits,
        })
        return template, payload

    def submit(self, principal: Principal, request: SubmitRequest, idem_key: str) -> dict:
        request = SubmitRequest.model_validate(request)
        self.authorize(principal, request.workspace, "task:create")
        template, payload = self._prepare(request)

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

    def research(self, principal: Principal, request: SubmitRequest, idem_key: str) -> dict:
        request = SubmitRequest.model_validate(request)
        for scope in ("task:create", "task:execute", "report:register"):
            self.authorize(principal, request.workspace, scope)
        template = self._template(request.workspace, request.template)
        if not self._execution_status(template.config)["credentials_present"]:
            raise ValueError("model credentials are missing; configure models before starting research")
        result = self.submit(principal, request, idem_key)
        row = self.tasks.get(result["id"])
        if row["status"] in {"queued", "running"}:
            self.execution.start(result["id"], report_actor=principal.subject)
        elif row["status"] == "succeeded":
            self.tasks.request_report(result["id"], principal.subject)
            finalize_report(self.tasks, self.root, result["id"])
        return {**result, "status": self.tasks.get(result["id"])["status"],
                "execution_requested": row["status"] in {"queued", "running", "succeeded"}}

    def session(self, principal: Principal) -> dict:
        templates = []
        if "task:create" in principal.scopes:
            for name, entry in self._profiles(principal.workspace).items():
                template = self._template(principal.workspace, name, entry)
                templates.append({
                    **entry["profile"].model_dump(mode="json"),
                    "version": entry["version"], "source": "配置" if entry["version"] else "预置",
                    "models": {"quick": template.config["quick_think_llm"],
                               "deep": template.config["deep_think_llm"],
                               "version": template.config.get("model_settings_revision", "预置")},
                    "execution": self._execution_status(template.config),
                    "allow_listed_stocks": template.config["research_policy"].get("allow_listed_stocks", False),
                })
        self.identities.audit(principal, "session:read")
        instruments = {row["symbol"]: row for row in self.instrument_catalog(principal.workspace)}
        if any(t["allow_listed_stocks"] for t in templates):
            instruments.update({row["symbol"]: {**row, "name_source": "系统预置证券目录"}
                                for row in search(limit=24)["items"] if row["symbol"] not in instruments})
        return {"subject": principal.subject, "workspace": principal.workspace,
                "scopes": sorted(principal.scopes), "templates": templates,
                "investor_tools": True, "instruments": list(instruments.values()),
                "stock_catalog": catalog()[0],
                "research_today": datetime.now(UTC).date().isoformat(),
                "research_options": {"currencies": CURRENCIES, "benchmarks": BENCHMARKS}}

    def instrument_catalog(self, workspace):
        approved = {}
        for name, entry in self._profiles(workspace).items():
            for symbol in entry["profile"].tickers:
                approved.setdefault(symbol, []).append(name)
        return [{**instrument(symbol), "templates": names, "approval_source": "研究模板配置"}
                for symbol, names in approved.items()]

    def _stock_access(self, workspace):
        listed = any(self._template(workspace, name, entry).config["research_policy"].get(
            "allow_listed_stocks", False,
        ) for name, entry in self._profiles(workspace).items())
        return None if listed else {i["symbol"] for i in self.instrument_catalog(workspace)}

    def instruments(self, principal, *, query="", market="", limit=24, offset=0):
        self.authorize(principal, principal.workspace, "task:read")
        return search(query=query, market=market, allowed=self._stock_access(principal.workspace),
                      limit=limit, offset=offset)

    def investor_home(self, principal):
        self.authorize(principal, principal.workspace, "task:read")
        with database(self.tasks.path) as db:
            rows = db.execute("""SELECT t.id,t.payload,t.status,t.created,r.id AS report_id
                FROM tasks t LEFT JOIN reports r ON r.run_path=t.result_path
                WHERE t.workspace=? AND t.author=? ORDER BY t.created DESC,t.id DESC LIMIT 100""",
                              (principal.workspace, principal.subject)).fetchall()
        tasks = [{**{k: row[k] for k in ("id", "status", "created", "report_id")},
                  "mandate": json.loads(row["payload"])["mandate"]} for row in rows]
        approved = self._stock_access(principal.workspace)
        explicit = {i["symbol"] for i in self.instrument_catalog(principal.workspace)}
        watchlist = [{**item, **instrument(item["symbol"]),
                      "approved": item["symbol"] in explicit
                      or approved is None and security(item["symbol"]) is not None
                      or approved is not None and item["symbol"] in approved,
                      "latest_task": next((t for t in tasks
                                           if t["mandate"]["ticker"] == item["symbol"]), None)}
                     for item in self.watchlists.list(principal)]
        # For a rarely researched symbol, use its own actual latest task even if
        # it lies outside the first hundred personal records.
        for item in watchlist:
            if item["latest_task"] is None:
                with database(self.tasks.path) as db:
                    row = db.execute("""SELECT t.id,t.payload,t.status,t.created,r.id AS report_id
                        FROM tasks t LEFT JOIN reports r ON r.run_path=t.result_path
                        WHERE t.workspace=? AND t.author=?
                        AND json_extract(t.payload,'$.mandate.ticker')=?
                        ORDER BY t.created DESC,t.id DESC LIMIT 1""",
                                     (principal.workspace, principal.subject, item["symbol"])).fetchone()
                if row:
                    item["latest_task"] = {
                        **{k: row[k] for k in ("id", "status", "created", "report_id")},
                        "mandate": json.loads(row["payload"])["mandate"],
                    }
        return {"recent": tasks[:8], "watchlist": watchlist}

    def change_watchlist(self, principal, data: WatchlistInput):
        self.authorize(principal, principal.workspace, "task:create")
        allowed = self._stock_access(principal.workspace)
        if allowed is None:
            allowed = set(catalog()[1]) | {i["symbol"] for i in self.instrument_catalog(principal.workspace)}
        result = self.watchlists.change(principal, WatchlistInput.model_validate(data), allowed)
        self.identities.audit(principal, "watchlist:" + result["action"], result["symbol"])
        return result

    @staticmethod
    def _pagination(limit: int, offset: int):
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("invalid pagination")

    def list_tasks(self, principal: Principal, *, limit=50, offset=0) -> dict:
        self.authorize(principal, principal.workspace, "task:read")
        self._pagination(limit, offset)
        with database(self.tasks.path) as db:
            total = db.execute("SELECT COUNT(*) FROM tasks WHERE workspace=?",
                               (principal.workspace,)).fetchone()[0]
            rows = db.execute("""SELECT t.*,r.id AS report_id FROM tasks t
                LEFT JOIN reports r ON r.run_path=t.result_path
                WHERE t.workspace=? ORDER BY t.created DESC,t.id DESC LIMIT ? OFFSET ?""",
                              (principal.workspace, limit, offset)).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["payload"])
            items.append({
                **{key: row[key] for key in ("id", "author", "status", "created", "deadline",
                                             "attempt_count", "error_type", "report_id")},
                "mandate": payload["mandate"], "experiment": payload["experiment"],
                "execution": self._execution_status(payload["config"]),
            })
        self.identities.audit(principal, "task:list")
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def execute(self, principal: Principal, task_id: str) -> dict:
        row = self.tasks.get(task_id)
        self.authorize(principal, row["workspace"], "task:execute", task_id)
        if row["status"] not in {"queued", "running"}:
            raise ValueError("only queued or running tasks can be requested")
        if not self._execution_status(row["payload"]["config"])["credentials_present"]:
            raise ValueError("model credentials are missing")
        if "report:register" in principal.scopes:
            self.execution.start(task_id, report_actor=principal.subject)
        elif row["status"] == "queued":
            self.execution.start(task_id)
        self.identities.audit(principal, "task:execute", task_id)
        return {"id": task_id, "status": self.tasks.get(task_id)["status"],
                "execution_requested": True}

    def list_reports(self, principal: Principal, *, limit=50, offset=0) -> dict:
        self.authorize(principal, principal.workspace, "report:read")
        self._pagination(limit, offset)
        with database(self.tasks.path) as db:
            total = db.execute("SELECT COUNT(*) FROM reports WHERE workspace=?",
                               (principal.workspace,)).fetchone()[0]
            rows = db.execute("SELECT * FROM reports WHERE workspace=? "
                              "ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                              (principal.workspace, limit, offset)).fetchall()
        items = []
        for row in rows:
            report = self.reports.get(row["id"])
            path = Path(report["run_path"])
            manifest = verify_run(path, report["manifest_hash"])
            inputs = json.loads((path / "input.json").read_bytes())
            quality = json.loads((path / "quality.json").read_bytes())
            items.append({**{key: report[key] for key in (
                "id", "author", "status", "expired", "created_at", "manifest_hash", "supersedes",
            )}, "mandate": inputs["mandate"], "rating": manifest["rating"],
                          "quality_status": quality["status"]})
        self.identities.audit(principal, "report:list")
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def list_experiments(self, principal: Principal, *, limit=50, offset=0) -> dict:
        self.authorize(principal, principal.workspace, "evaluation:read")
        self._pagination(limit, offset)
        with database(self.tasks.path) as db:
            total = db.execute("SELECT COUNT(*) FROM experiments WHERE workspace=?",
                               (principal.workspace,)).fetchone()[0]
            rows = db.execute("SELECT id FROM experiments WHERE workspace=? "
                              "ORDER BY rowid DESC LIMIT ? OFFSET ?",
                              (principal.workspace, limit, offset)).fetchall()
        items = []
        for row in rows:
            experiment = self.evaluations.experiment(row["id"])
            plan = experiment["plan"]
            items.append({"id": row["id"], "name": plan["experiment"], "mode": plan["mode"],
                          "sample_count": len(plan["samples"]),
                          "registered_at": experiment["registered_at"]})
        self.identities.audit(principal, "evaluation:list")
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @staticmethod
    def _input_summary(payload):
        config = payload.get("config", {})
        return {
            "analysts": payload.get("selected_analysts", payload.get("analysts", [])),
            "portfolio": payload.get("portfolio"),
            "allocation_valuation": payload.get("allocation_valuation"),
            "limits": payload.get("limits"),
            "models": {tier: config.get(f"{tier}_think_llm") for tier in ("quick", "deep")},
            "template_revision": config.get("research_settings_revision", "预置"),
            "execution_mode": config.get("execution_mode", "full"),
            "display_currency": config.get("display_currency"),
            "stock_question": config.get("stock_question"),
            "security": config.get("selected_security"),
        }

    def task(self, principal: Principal, task_id: str) -> dict:
        row = self.tasks.get(task_id)
        self.authorize(principal, row["workspace"], "task:read", task_id)
        self.identities.audit(principal, "task:read", task_id)
        stages = [json.loads(e["detail"])["stage"] for e in row["events"] if e["action"] == "stage"]
        with database(self.tasks.path) as db:
            report = db.execute("SELECT id FROM reports WHERE run_path=?",
                                (row["result_path"],)).fetchone()
        return {**{k: row[k] for k in (
            "id", "workspace", "author", "status", "created", "deadline", "attempt_count",
            "error_type", "manifest_hash",
        )}, "mandate": row["payload"]["mandate"], "calls": len(row["calls"]),
            "experiment": row["payload"]["experiment"],
            "inputs": self._input_summary(row["payload"]),
            "execution": self._execution_status(row["payload"]["config"]),
            "report_id": report["id"] if report else None,
            "progress": {"stage": STAGES.get(stages[-1]) if stages else None,
                         "stages": list(dict.fromkeys(STAGES[s] for s in stages)),
                         "max_calls": row["payload"]["limits"]["max_calls"]},
            "events": [{**{key: event[key] for key in ("at", "action")},
                        **({"stage": STAGES.get(json.loads(event["detail"])["stage"])}
                           if event["action"] == "stage" else {})} for event in row["events"]]}

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
        manifest = verify_run(path, row["manifest_hash"])
        self.identities.audit(principal, "report:read", report_id)
        text_path = path / "report" / "complete_report.md"
        original = json.loads((path / "input.json").read_bytes())
        with database(self.tasks.path) as db:
            task = db.execute("SELECT id FROM tasks WHERE result_path=?", (str(path),)).fetchone()
        inputs = self._input_summary(self.tasks.get(task["id"])["payload"] if task else original)
        quality = json.loads((path / "quality.json").read_bytes())
        return {**{k: row[k] for k in (
            "id", "workspace", "author", "status", "expired", "manifest_hash", "supersedes",
        )}, "events": row["events"], "quality": quality,
                "brief": report_brief(path, manifest, original["mandate"], quality),
                "report_markdown": text_path.read_text() if text_path.exists() else "",
                "mandate": original["mandate"], "inputs": inputs,
                "rating": json.loads((path / "run.json").read_bytes())["rating"]}

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
            template = self._template(plan.workspace, sample.template)
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
            "controls": {kind: self._control_state(principal.workspace, kind) for kind in
                         ("pause_submissions", "freeze_publication")},
        }

    def _control_state(self, workspace, kind):
        with database(self.tasks.path) as db:
            return self._enabled(db, workspace, kind)

    def audit(self, principal: Principal) -> list[dict]:
        self.authorize(principal, principal.workspace, "audit:read")
        self.identities.audit(principal, "audit:read")
        with database(self.tasks.path) as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM access_events WHERE workspace=? ORDER BY seq DESC LIMIT 200",
                (principal.workspace,))]
