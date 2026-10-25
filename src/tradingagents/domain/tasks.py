"""Validated local task inputs and conservative admission limits."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tradingagents.domain.quality import AllocationInput, AllocationValuation, ResearchPolicy
from tradingagents.domain.research import ResearchMandate
from tradingagents.infrastructure.artifacts import component, json_bytes
from tradingagents.portfolio import PortfolioContext


class TaskLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int = Field(default=80, strict=True, ge=1, le=1000)
    max_attempts: int = Field(default=2, strict=True, ge=1, le=10)
    max_seconds: int = Field(default=1800, strict=True, ge=1, le=86400)
    max_output_tokens: int = Field(default=4096, strict=True, ge=1, le=65536)
    # Integer micro-USD: reservations are admission controls, not vendor invoices.
    budget_microusd: int = Field(default=10_000_000, strict=True, ge=1)
    reserve_per_call_microusd: int = Field(default=500_000, strict=True, ge=1)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: str
    experiment: str
    mandate: ResearchMandate
    config: dict
    selected_analysts: tuple[Literal["market", "social", "news", "fundamentals"], ...] = (
        "market", "social", "news", "fundamentals",
    )
    portfolio: PortfolioContext | None = None
    allocation: AllocationInput | None = None
    allocation_valuation: AllocationValuation | None = None
    limits: TaskLimits = Field(default_factory=TaskLimits)

    @field_validator("workspace", "experiment")
    @classmethod
    def _scope(cls, value):
        return component(value)

    @model_validator(mode="after")
    def _valid(self):
        self.mandate.validate_run(
            self.mandate.ticker, self.mandate.analysis_date, self.mandate.asset_type,
        )
        ResearchPolicy.model_validate(self.config.get("research_policy", {}))
        if not self.selected_analysts or len(set(self.selected_analysts)) != len(self.selected_analysts):
            raise ValueError("analysts must be nonempty and unique")
        json_bytes(self.config)  # Reject non-JSON configuration and NaN/Infinity.
        return self
