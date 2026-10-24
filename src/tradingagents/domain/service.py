"""Public request contracts; runtime configuration is operator-owned."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.domain.research import ResearchMandate
from tradingagents.domain.tasks import TaskLimits
from tradingagents.portfolio import PortfolioContext


class ResearchTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config: dict
    limits: TaskLimits = Field(default_factory=TaskLimits)
    analysts: tuple[str, ...] = ("market", "social", "news", "fundamentals")
    max_pending: int = Field(default=20, strict=True, ge=1)
    workspace_budget_microusd: int = Field(default=100_000_000, strict=True, ge=1)


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: str
    experiment: str
    template: str
    mandate: ResearchMandate
    portfolio: PortfolioContext | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["approved", "rejected", "published", "withdrawn"]
    reason: str = Field(min_length=1, max_length=4000)
    acknowledgements: tuple[str, ...] = ()


class CostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    amount_microusd: int = Field(strict=True, ge=0)
    invoice_ref: str = Field(min_length=1, max_length=200)
