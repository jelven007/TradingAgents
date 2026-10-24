from copy import deepcopy
from decimal import Decimal

import pytest

from tradingagents.domain.evaluation import ExperimentPlan, ObservationInput, evaluate_window


def plan_body(keys=("same",), mode="diagnostic"):
    return {
        "workspace": "research", "experiment": "control", "mode": mode,
        "price_basis": "split_adjusted_close", "calendar_source": "offline declared sessions",
        "calendar_evidence": "Fixture calendar only; no exchange calendar certification",
        "samples": [{
            "key": key, "template": "daily",
            "mandate": {"ticker": "NVDA", "analysis_date": "2026-01-09", "benchmark": "SPY",
                        "prediction_horizon_trading_days": 5, "quote_currency": "USD",
                        "valid_until": "2099-01-01"},
            "sessions": ["2026-01-12", "2026-01-13", "2026-01-14",
                         "2026-01-15", "2026-01-16", "2026-01-20"],
        } for key in keys],
    }


def observation_body(exit_session="2026-01-20"):
    return {
        "entry_session": "2026-01-12", "exit_session": exit_session,
        "asset": {"symbol": "NVDA", "currency": "USD", "basis": "split_adjusted_close",
                  "entry": "100", "exit": "110"},
        "benchmark": {"symbol": "SPY", "currency": "USD", "basis": "split_adjusted_close",
                      "entry": "200", "exit": "210"},
        "source": "offline fixture", "source_payload": "NVDA:100->110;SPY:200->210;USD;fixture",
    }


def test_full_window_decimal_returns_and_short_window_is_interim():
    plan = ExperimentPlan.model_validate(plan_body())
    final = evaluate_window(plan.samples[0], plan.price_basis,
                            ObservationInput.model_validate(observation_body()))
    assert final["window"] == "final"
    assert Decimal(final["asset_return"]) == Decimal("0.1")
    assert Decimal(final["benchmark_return"]) == Decimal("0.05")
    assert Decimal(final["excess_return"]) == Decimal("0.05")
    interim = evaluate_window(plan.samples[0], plan.price_basis, ObservationInput.model_validate(
        observation_body("2026-01-13")))
    assert interim["window"] == "interim" and interim["elapsed_sessions"] == 1
    assert "NAV" in final["return_scope"] and "sharpe" not in final


@pytest.mark.parametrize("change", [
    {"entry_session": "2026-01-09"}, {"exit_session": "2026-01-19"},
    {"exit_session": "2026-01-21"},
    {"asset": {"currency": "HKD"}}, {"benchmark": {"currency": "HKD"}},
    {"asset": {"symbol": "MSFT"}}, {"benchmark": {"symbol": "QQQ"}},
    {"asset": {"basis": "unadjusted_close"}},
    {"benchmark": {"basis": "total_return_index"}},
])
def test_mismatched_window_identity_currency_and_adjustment_are_rejected(change):
    body = observation_body()
    for key, value in change.items():
        body[key] = {**body[key], **value} if isinstance(value, dict) else value
    plan = ExperimentPlan.model_validate(plan_body())
    with pytest.raises(ValueError):
        evaluate_window(plan.samples[0], plan.price_basis, ObservationInput.model_validate(body))


@pytest.mark.parametrize("price", ["NaN", "Infinity", "0", "-1", "1e19", "0.0000000000001", 1.5, True])
def test_prices_reject_nonfinite_nonpositive_lossy_or_unbounded_input(price):
    body = observation_body()
    body["asset"]["entry"] = price
    with pytest.raises(ValueError):
        ObservationInput.model_validate(body)


@pytest.mark.parametrize("change", ["duplicate", "unsorted", "short", "same_day", "expired", "key"])
def test_plan_calendar_and_sample_contract_are_fixed(change):
    body = deepcopy(plan_body())
    sample = body["samples"][0]
    if change == "duplicate":
        sample["sessions"][1] = sample["sessions"][0]
    elif change == "unsorted":
        sample["sessions"].reverse()
    elif change == "short":
        sample["sessions"].pop()
    elif change == "same_day":
        sample["sessions"][0] = "2026-01-09"
    elif change == "expired":
        sample["mandate"]["valid_until"] = "2026-01-10"
    else:
        body["samples"].append(deepcopy(sample))
    with pytest.raises(ValueError):
        ExperimentPlan.model_validate(body)
