"""Frozen evaluation inputs; explicit sessions do not imply an exchange calendar."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.domain.research import ResearchMandate, canonical_date, canonical_symbol
from tradingagents.infrastructure.artifacts import component

PriceBasis = Literal["unadjusted_close", "split_adjusted_close", "total_return_index"]


class SamplePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    template: str = "daily"
    mandate: ResearchMandate
    sessions: tuple[str, ...] = Field(min_length=2, max_length=2521)

    @field_validator("key", "template")
    @classmethod
    def _key(cls, value):
        return component(value)

    @field_validator("sessions")
    @classmethod
    def _sessions(cls, value):
        return tuple(canonical_date(v) for v in value)

    @model_validator(mode="after")
    def _window(self):
        if len(self.sessions) != self.mandate.prediction_horizon_trading_days + 1:
            raise ValueError("sessions must contain entry plus the full mandated horizon")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("sessions must be strictly increasing and unique")
        if self.sessions[0] <= self.mandate.analysis_date:
            raise ValueError("entry session must follow the daily research date")
        if self.mandate.valid_until < self.sessions[0]:
            raise ValueError("research must remain valid at the entry session")
        return self


class ExperimentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    workspace: str
    experiment: str
    mode: Literal["prospective", "diagnostic"]
    samples: tuple[SamplePlan, ...] = Field(min_length=1, max_length=200)
    price_basis: PriceBasis
    calendar_source: str = Field(min_length=1, max_length=200)
    calendar_evidence: str = Field(min_length=1, max_length=24000)

    @field_validator("workspace", "experiment")
    @classmethod
    def _component(cls, value):
        return component(value)

    @model_validator(mode="after")
    def _keys(self):
        if len({s.key for s in self.samples}) != len(self.samples):
            raise ValueError("planned sample keys must be unique")
        return self


class PricePair(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    basis: PriceBasis
    entry: Decimal = Field(gt=0, le=Decimal("1e18"), max_digits=31, decimal_places=12)
    exit: Decimal = Field(gt=0, le=Decimal("1e18"), max_digits=31, decimal_places=12)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value):
        return canonical_symbol(value)

    @field_validator("entry", "exit", mode="before")
    @classmethod
    def _decimal(cls, value):
        if isinstance(value, (float, bool)) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("prices require decimal strings or integers, not binary floats")
        return value


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_session: str
    exit_session: str
    asset: PricePair
    benchmark: PricePair
    source: str = Field(min_length=1, max_length=200)
    source_payload: str = Field(min_length=1, max_length=24000)

    @field_validator("entry_session", "exit_session")
    @classmethod
    def _date(cls, value):
        return canonical_date(value)


def evaluate_window(sample: SamplePlan, basis: PriceBasis, data: ObservationInput) -> dict:
    """Comparable simple returns, never portfolio NAV or a transaction simulation."""
    mandate = sample.mandate
    if data.entry_session != sample.sessions[0] or data.exit_session not in sample.sessions[1:]:
        raise ValueError("observation must use the frozen entry and a planned exit session")
    if (data.asset.symbol, data.benchmark.symbol) != (mandate.ticker, mandate.benchmark):
        raise ValueError("asset and benchmark identities must match the mandate")
    if data.asset.currency != mandate.quote_currency or data.benchmark.currency != mandate.quote_currency:
        raise ValueError("asset and benchmark require the same mandated quote currency")
    if data.asset.basis != basis or data.benchmark.basis != basis:
        raise ValueError("asset and benchmark require the same frozen price basis")
    with localcontext() as ctx:
        ctx.prec = 50
        asset_return = data.asset.exit / data.asset.entry - 1
        benchmark_return = data.benchmark.exit / data.benchmark.entry - 1
        excess = asset_return - benchmark_return
    elapsed = sample.sessions.index(data.exit_session)
    return {
        "window": "final" if elapsed == mandate.prediction_horizon_trading_days else "interim",
        "elapsed_sessions": elapsed, "horizon_sessions": mandate.prediction_horizon_trading_days,
        "asset_return": str(asset_return), "benchmark_return": str(benchmark_return),
        "excess_return": str(excess), "currency": mandate.quote_currency, "price_basis": basis,
        "return_scope": "simple matched-window observation; no positions, costs or portfolio NAV",
    }
