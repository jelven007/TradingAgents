"""Safe, typed workspace research profiles and per-run reductions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.domain.research import canonical_symbol
from tradingagents.domain.tasks import TaskLimits
from tradingagents.infrastructure.artifacts import component

ANALYSTS = ("market", "social", "news", "fundamentals")
ASSETS = ("stock", "crypto")
PURPOSES = ("general_research", "event_research", "portfolio_review")
CURRENCIES = ("USD", "CNY", "HKD", "EUR", "JPY", "GBP")
BENCHMARKS = ("SPY", "QQQ", "^HSI", "000300.SS", "BTC-USD")


class InputError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field, self.message = field, message


class ResearchDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ticker: str = ""
    asset_type: Literal["stock", "crypto"] = "stock"
    purpose: Literal["general_research", "event_research", "portfolio_review"] = "general_research"
    quote_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    benchmark: str = "SPY"
    prediction_horizon_trading_days: int = Field(default=5, strict=True, ge=1, le=2520)
    valid_days: int = Field(default=30, strict=True, ge=0, le=3650)

    @field_validator("ticker", "benchmark")
    @classmethod
    def symbols(cls, value):
        return canonical_symbol(value) if value else value


class ResearchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    tickers: tuple[str, ...] = Field(default=(), max_length=1000)
    asset_types: tuple[Literal["stock", "crypto"], ...] = ("stock", "crypto")
    purposes: tuple[Literal["general_research", "event_research", "portfolio_review"], ...] = PURPOSES
    defaults: ResearchDefaults = Field(default_factory=ResearchDefaults)
    analysts: tuple[Literal["market", "social", "news", "fundamentals"], ...] = ANALYSTS
    limits: TaskLimits = Field(default_factory=TaskLimits)
    max_pending: int = Field(default=20, strict=True, ge=1, le=1000)
    workspace_budget_microusd: int = Field(default=100_000_000, strict=True, ge=1)

    @field_validator("name")
    @classmethod
    def name_component(cls, value):
        return component(value)

    @field_validator("tickers")
    @classmethod
    def tickers_normalized(cls, values):
        return tuple(canonical_symbol(value) for value in values)

    @model_validator(mode="after")
    def consistent(self):
        for field in ("asset_types", "purposes", "analysts"):
            values = getattr(self, field)
            if not values or len(set(values)) != len(values):
                raise InputError(field, "至少选择一项，且不能重复。")
        if len(set(self.tickers)) != len(self.tickers):
            raise InputError("tickers", "批准标的不能重复。")
        if self.defaults.ticker and self.defaults.ticker not in self.tickers:
            raise InputError("defaults.ticker", "默认标的必须在批准清单中。")
        if self.tickers and not self.defaults.ticker:
            raise InputError("defaults.ticker", "请指定默认标的。")
        if not self.defaults.benchmark:
            raise InputError("defaults.benchmark", "请填写对照基准。")
        if self.defaults.asset_type not in self.asset_types:
            raise InputError("defaults.asset_type", "默认资产类型必须在允许范围内。")
        if self.defaults.purpose not in self.purposes:
            raise InputError("defaults.purpose", "默认用途必须在允许范围内。")
        if self.limits.reserve_per_call_microusd > self.limits.budget_microusd:
            raise InputError("limits.budget_microusd", "任务预算至少要覆盖一次调用预留额。")
        if self.workspace_budget_microusd < self.limits.budget_microusd:
            raise InputError("workspace_budget_microusd", "工作空间预算不能低于单任务预算。")
        return self


class ResearchSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_version: int = Field(strict=True, ge=0)
    profile: ResearchProfile
    base_template: str | None = None

    @field_validator("base_template")
    @classmethod
    def base_component(cls, value):
        return component(value) if value is not None else value


class ResearchOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    execution_mode: Literal["guided_stock", "full"] = "full"
    display_currency: Literal["USD", "CNY"] = "USD"
    stock_question: Literal["understand", "buy", "hold", "sell"] = "understand"
    selected_analysts: tuple[Literal["market", "social", "news", "fundamentals"], ...] | None = None
    max_calls: int | None = Field(default=None, strict=True, ge=1, le=1000)
    max_seconds: int | None = Field(default=None, strict=True, ge=1, le=86400)
    max_output_tokens: int | None = Field(default=None, strict=True, ge=1, le=65536)
    budget_microusd: int | None = Field(default=None, strict=True, ge=1)
