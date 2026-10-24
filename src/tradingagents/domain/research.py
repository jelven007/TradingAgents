"""Explicit daily research mandate shared by prompts, reports and evaluation."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def canonical_symbol(value: str) -> str:
    """Validate identity spelling without silently substituting another instrument."""
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9._^=+-]{0,31}", value):
        raise ValueError("symbol must be 1-32 letters/digits or supported exchange punctuation")
    return value


def canonical_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must use YYYY-MM-DD")
    date.fromisoformat(value)
    return value


class ResearchMandate(BaseModel):
    """An opt-in contract; daily data cannot certify an intraday information cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    ticker: str
    analysis_date: str
    asset_type: Literal["stock", "crypto"] = "stock"
    purpose: Literal["general_research", "event_research", "portfolio_review"] = "general_research"
    prediction_horizon_trading_days: int = Field(strict=True, ge=1, le=2520)
    benchmark: str
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$")
    valid_until: str
    time_granularity: Literal["daily"] = "daily"

    @field_validator("ticker", "benchmark")
    @classmethod
    def _symbol(cls, value: str) -> str:
        return canonical_symbol(value)

    @field_validator("analysis_date", "valid_until")
    @classmethod
    def _date(cls, value: str) -> str:
        return canonical_date(value)

    @model_validator(mode="after")
    def _window(self):
        if self.valid_until < self.analysis_date:
            raise ValueError("valid_until must not precede analysis_date")
        return self

    def validate_run(self, ticker: str, analysis_date: str, asset_type: str) -> None:
        if (canonical_symbol(ticker), str(analysis_date), asset_type) != (
            self.ticker, self.analysis_date, self.asset_type,
        ):
            raise ValueError("run inputs do not match the frozen research mandate")
        if self.analysis_date > datetime.now(UTC).date().isoformat():
            raise ValueError("analysis_date cannot be in the future")

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def render(self) -> str:
        return (
            f"Research mandate: {self.ticker}; analysis date {self.analysis_date}; "
            f"purpose {self.purpose}; prediction horizon "
            f"{self.prediction_horizon_trading_days} trading days; "
            f"benchmark {self.benchmark}; quote currency {self.quote_currency}; "
            f"valid until {self.valid_until}. "
            "This is daily research, not an intraday point-in-time claim. "
            "Use this horizon consistently. A shorter return window is an interim "
            "observation, not a final verdict on the thesis. "
            "Separate evidence gaps from Hold; do not invent prices or account constraints. "
            "A Sell rating is not authorization to open a short position."
        )


def mandate_from_config(config: dict) -> ResearchMandate | None:
    raw = config.get("research_mandate")
    return ResearchMandate.model_validate(raw) if raw is not None else None
