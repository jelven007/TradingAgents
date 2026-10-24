"""Versioned deterministic research controls, independent of agent judgments."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradingagents.domain.research import ResearchMandate, canonical_symbol
from tradingagents.infrastructure.artifacts import hash_component, read_verified
from tradingagents.infrastructure.evidence import verify_bundle


class ResearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(default="local-research-v1", min_length=1, max_length=100)
    approved_tickers: tuple[str, ...] = ()
    max_price_age_calendar_days: int = Field(default=7, strict=True, ge=0, le=31)
    require_licensed_sources: bool = True
    long_only: bool = True
    max_position_weight: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)

    @field_validator("approved_tickers")
    @classmethod
    def _symbols(cls, symbols):
        return tuple(canonical_symbol(symbol) for symbol in symbols)


class AllocationInput(BaseModel):
    """Explicit valuation contract; never inferred from free-text position sizing."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    ticker: str
    valuation_date: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price: Decimal = Field(gt=0)
    equity: Decimal = Field(gt=0)
    current_units: Decimal
    change_units: Decimal
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def calculate_allocation(value: AllocationInput, policy: ResearchPolicy) -> dict:
    """Decimal arithmetic in one currency; a Sell label alone is never an order."""
    value = AllocationInput.model_validate(value)
    units = value.current_units + value.change_units
    notional = units * value.price
    weight = abs(notional) / value.equity
    return {
        "formula_version": 1, "formula": "(current_units + change_units) * price / equity",
        "inputs": value.model_dump(mode="json"), "target_units": str(units),
        "target_notional": str(notional), "absolute_weight": str(weight),
        "long_only_pass": not policy.long_only or units >= 0,
        "concentration_pass": weight <= policy.max_position_weight,
    }


def finite_number(value) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("non-finite decimal")
    return number


def check_research(
    mandate: ResearchMandate, state: dict, evidence_path: Path, evidence_hash: str,
    policy: ResearchPolicy, *, allocation: AllocationInput | None = None,
) -> dict:
    """Block observable violations; require human attestation for unverified prose.

    The current graph does not bind every natural-language number to a calculation.
    A passing deterministic subset must never be labeled fully verified research.
    """
    issues = []
    calculations = []

    def add(code: str, severity: Literal["block", "review"], detail: str):
        issues.append({"code": code, "severity": severity, "detail": detail})

    bundle = verify_bundle(evidence_path, evidence_hash)
    if mandate.ticker not in policy.approved_tickers:
        add("out_of_scope", "block", "Ticker is absent from the approved research universe.")
    if state.get("company_of_interest", "").upper() != mandate.ticker or (
        state.get("trade_date") != mandate.analysis_date
    ):
        add("identity_mismatch", "block", "Decision identity/date differs from the mandate.")
    if state.get("research_mandate") != mandate.model_dump(mode="json"):
        add("mandate_mismatch", "block", "Decision does not carry the frozen research mandate.")
    if state.get("final_rating") not in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}:
        add("unparsed_rating", "block", "The recommendation is not a supported research rating.")
    if not state.get("final_trade_decision", "").strip():
        add("missing_decision", "block", "No decision text.")

    facts = []
    for record in bundle["records"]:
        ref = hash_component(record["content_sha256"])
        output = json.loads(read_verified(evidence_path / "blobs" / f"{ref}.json", ref))
        internal = record["source"] in {"memory", "news_prefetch"}
        if record["status"] == "error":
            add("vendor_failure", "review", f"{record['source']}/{record['method']} failed.")
            continue
        license_label = record["license"]
        licensed = (isinstance(license_label, str) and bool(license_label.strip())
                    and license_label.strip().lower() != "unknown")
        if policy.require_licensed_sources and not internal and not licensed:
            add("unknown_license", "block", f"No storage/use license label for {record['source']}.")
        if not internal and record["known_at"] is None:
            add("unknown_publication_time", "review",
                "Captured output does not certify when it first became public.")
        if isinstance(output, str) and re.search(r"DATA_UNAVAILABLE|NO_DATA_AVAILABLE|<unavailable>", output):
            add("unavailable_source", "review", f"{record['source']}/{record['method']} is unavailable.")
        if record["method"] == "verified_market_facts":
            facts.append((ref, output))

    if not facts:
        add("missing_verified_prices", "block", "No structured verified OHLCV facts were captured.")
    observed_closes = {}
    validated_facts = {}
    for ref, fact in facts:
        try:
            if fact["ticker"] != mandate.ticker or fact["as_of_date"] != mandate.analysis_date:
                raise ValueError("price identity/date mismatch")
            age = (date.fromisoformat(mandate.analysis_date) - date.fromisoformat(fact["price_date"])).days
            if age < 0:
                add("future_price", "block", "A price row is after the analysis date.")
            elif age > policy.max_price_age_calendar_days:
                add("stale_price", "block", f"Latest price is {age} calendar days old.")
            values = {key: finite_number(fact["values"][key])
                      for key in ("Open", "High", "Low", "Close", "Volume")}
            if any(values[key] <= 0 for key in ("Open", "High", "Low", "Close")) or values["Volume"] < 0:
                raise ValueError("invalid OHLCV sign")
            if not (values["Low"] <= min(values["Open"], values["Close"])
                    <= max(values["Open"], values["Close"]) <= values["High"]):
                raise ValueError("OHLC range inconsistent")
            observed_closes.setdefault(fact["price_date"], set()).add(values["Close"])
            if fact["currency"] is None:
                add("unverified_currency", "review", "Price currency is not supplied by this data adapter.")
            elif fact["currency"] != mandate.quote_currency:
                add("currency_mismatch", "block", "Price currency differs from mandate.")
            calculations.append({"check": "OHLCV", "evidence_sha256": ref,
                                 "price_date": fact["price_date"], "age_calendar_days": age,
                                 "close": str(values["Close"])})
            validated_facts[ref] = fact
        except (KeyError, TypeError, ValueError) as exc:
            add("invalid_market_facts", "block", f"Structured price facts rejected: {exc}.")
    if any(len(values) > 1 for values in observed_closes.values()):
        add("conflicting_prices", "block", "Verified sources disagree on the same day's close.")

    # Validate only the explicit schema labels, without guessing prose meaning.
    texts = (state.get("final_trade_decision", ""), state.get("trader_investment_plan", ""))
    for text in texts:
        for label, value in re.findall(r"^\*\*(Price Target|Entry Price|Stop Loss)\*\*:\s*(.*)$", text, re.M):
            if value.strip().lower() in {"not provided", "none", "n/a"}:
                continue
            try:
                if finite_number(value.strip()) <= 0:
                    raise ValueError("non-positive price")
            except ValueError:
                add("invalid_proposed_price", "block", f"{label} is not a finite positive price.")
            else:
                add("unverified_proposed_price", "review", f"{label} has no linked valuation model.")

    if allocation is not None:
        allocation = AllocationInput.model_validate(allocation)
        matches = [fact for ref, fact in validated_facts.items() if ref == allocation.evidence_sha256]
        if (allocation.ticker != mandate.ticker or allocation.currency != mandate.quote_currency
                or allocation.valuation_date != mandate.analysis_date or not matches):
            add("allocation_input_mismatch", "block", "Allocation lacks matching identity, currency, date or evidence.")
        elif (matches[0].get("price_date") != allocation.valuation_date
              or matches[0].get("currency") != allocation.currency
              or finite_number(matches[0]["values"]["Close"]) != allocation.price):
            add("allocation_price_mismatch", "block", "Allocation price/currency is not the verified close.")
        calculation = calculate_allocation(allocation, policy)
        calculations.append(calculation)
        if not calculation["long_only_pass"]:
            add("short_position", "block", "Target units violate the long-only policy.")
        if not calculation["concentration_pass"]:
            add("concentration", "block", "Target position exceeds the approved equity fraction.")
    elif mandate.purpose == "portfolio_review":
        add("missing_account_valuation", "block", "Portfolio review requires an explicit verified allocation input.")
    else:
        add("account_not_assessed", "review", "General research is not an executable account allocation.")
    add("unverified_narrative", "review", "Human review must verify claims, references, horizon and invalidation conditions.")
    unique = {json.dumps(issue, sort_keys=True): issue for issue in issues}
    issues = list(unique.values())
    return {
        "schema_version": 1, "policy": policy.model_dump(mode="json"),
        "status": "blocked" if any(i["severity"] == "block" for i in issues) else "needs_review",
        "issues": issues, "calculations": calculations, "evidence_sha256": evidence_hash,
        "publication_requires_human_review": True,
    }
