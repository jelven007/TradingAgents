from decimal import Decimal

import pytest

from tradingagents.domain.quality import (
    AllocationInput,
    ResearchPolicy,
    calculate_allocation,
    check_research,
)
from tradingagents.domain.research import ResearchMandate
from tradingagents.infrastructure.evidence import EvidenceRecorder


@pytest.fixture
def mandate():
    return ResearchMandate(ticker="NVDA", analysis_date="2026-01-09",
                            prediction_horizon_trading_days=20, benchmark="QQQ",
                            quote_currency="USD", valid_until="2099-01-01")


def evaluate(tmp_path, mandate, *, changes=None, text=None, policy=None, extra_fact=None):
    facts = {"ticker": "NVDA", "as_of_date": "2026-01-09", "price_date": "2026-01-09",
             "currency": "USD", "values": {"Open": "100", "High": "110", "Low": "90",
                                          "Close": "105", "Volume": "100000"}}
    facts.update(changes or {})
    recorder = EvidenceRecorder(tmp_path, {"yfinance": "test-license"})
    recorder.record("yfinance", "verified_market_facts", {}, facts)
    if extra_fact:
        recorder.record("yfinance", "verified_market_facts", {}, {**facts, **extra_fact})
    _, ref = recorder.seal()
    state = {"company_of_interest": mandate.ticker, "trade_date": mandate.analysis_date,
             "research_mandate": mandate.model_dump(mode="json"), "final_rating": "Buy",
             "final_trade_decision": text or "**Rating**: Buy"}
    return check_research(mandate, state, tmp_path, ref,
                          policy or ResearchPolicy(approved_tickers=("NVDA",)))


def test_valid_prices_still_require_narrative_review(tmp_path, mandate):
    result = evaluate(tmp_path, mandate)
    assert result["status"] == "needs_review"
    assert not [i for i in result["issues"] if i["severity"] == "block"]
    assert result["calculations"][0]["close"] == "105"
    assert "unverified_narrative" in {i["code"] for i in result["issues"]}


@pytest.mark.parametrize(("changes", "code"), [
    ({"price_date": "2026-01-10"}, "future_price"),
    ({"price_date": "2025-12-20"}, "stale_price"),
    ({"price_date": "not-a-date"}, "invalid_market_facts"),
    ({"ticker": "MSFT"}, "invalid_market_facts"),
    ({"currency": "HKD"}, "currency_mismatch"),
    ({"values": {"Open": "100", "High": "110", "Low": "90", "Close": "NaN", "Volume": "1"}},
     "invalid_market_facts"),
    ({"values": {"Open": "100", "High": "110", "Low": "90", "Close": "120", "Volume": "1"}},
     "invalid_market_facts"),
    ({"values": {"Open": "100", "High": "110", "Low": "90", "Close": "100", "Volume": "-1"}},
     "invalid_market_facts"),
])
def test_bad_facts_block_publication(tmp_path, mandate, changes, code):
    result = evaluate(tmp_path, mandate, changes=changes)
    assert result["status"] == "blocked"
    assert code in {i["code"] for i in result["issues"]}


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0", "around 100", "20%"])
def test_explicit_invalid_price_is_not_approved_by_a_buy_rating(tmp_path, mandate, price):
    result = evaluate(tmp_path, mandate, text=f"**Rating**: Buy\n\n**Price Target**: {price}")
    assert result["status"] == "blocked"
    assert "invalid_proposed_price" in {i["code"] for i in result["issues"]}


def test_conflicting_closes_are_not_voted_away(tmp_path, mandate):
    result = evaluate(tmp_path, mandate, extra_fact={
        "values": {"Open": "100", "High": "110", "Low": "90", "Close": "104", "Volume": "1"},
    })
    assert "conflicting_prices" in {i["code"] for i in result["issues"]}
    assert result["status"] == "blocked"


def test_empty_approved_universe_fails_closed(tmp_path, mandate):
    result = evaluate(tmp_path, mandate, policy=ResearchPolicy())
    assert "out_of_scope" in {i["code"] for i in result["issues"]}


def test_portfolio_review_cannot_invent_equity(tmp_path, mandate):
    result = evaluate(tmp_path, mandate.model_copy(update={"purpose": "portfolio_review"}))
    assert "missing_account_valuation" in {i["code"] for i in result["issues"]}


@pytest.mark.parametrize(("change", "long_only", "concentration"), [
    ("0", True, True), ("0.001", True, False), ("-10", True, True), ("-10.001", False, True),
])
def test_decimal_allocation_boundaries(change, long_only, concentration):
    value = AllocationInput(ticker="NVDA", valuation_date="2026-01-09", currency="USD",
                            price="100", equity="10000", current_units="10",
                            change_units=change, evidence_sha256="a" * 64)
    result = calculate_allocation(value, ResearchPolicy())
    assert result["long_only_pass"] is long_only
    assert result["concentration_pass"] is concentration
    assert Decimal(result["target_units"]) == Decimal("10") + Decimal(change)


@pytest.mark.parametrize("equity", ["NaN", "Infinity", "0", "-1"])
def test_invalid_valuation_is_rejected(equity):
    with pytest.raises(ValueError):
        AllocationInput(ticker="NVDA", valuation_date="2026-01-09", currency="USD",
                        price="100", equity=equity, current_units="1",
                        change_units="0", evidence_sha256="a" * 64)


@pytest.mark.parametrize("currency", ["USD", None, "HKD"])
def test_allocation_must_reference_actual_price_and_currency(tmp_path, mandate, currency):
    facts = {"ticker": "NVDA", "as_of_date": "2026-01-09", "price_date": "2026-01-09",
             "currency": currency, "values": {"Open": "100", "High": "110", "Low": "90",
                                              "Close": "100", "Volume": "1"}}
    recorder = EvidenceRecorder(tmp_path, {"test": "licensed-fixture"})
    recorder.record("test", "verified_market_facts", {}, facts)
    bundle, ref = recorder.seal()
    allocation = AllocationInput(ticker="NVDA", valuation_date="2026-01-09", currency="USD",
                                 price="100", equity="10000", current_units="10", change_units="0",
                                 evidence_sha256=bundle["records"][0]["content_sha256"])
    state = {"company_of_interest": "NVDA", "trade_date": mandate.analysis_date,
             "research_mandate": mandate.model_dump(mode="json"),
             "final_rating": "Sell", "final_trade_decision": "**Rating**: Sell"}
    result = check_research(mandate, state, tmp_path, ref,
                            ResearchPolicy(approved_tickers=("NVDA",)), allocation=allocation)
    assert (result["status"] == "needs_review") == (currency == "USD")
    # A Sell research rating did not change the provided target units.
    assert result["calculations"][-1]["target_units"] == "10"


def test_missing_evidence_and_unparsed_rating_cannot_publish(tmp_path, mandate):
    recorder = EvidenceRecorder(tmp_path)
    _, ref = recorder.seal()
    result = check_research(mandate, {"company_of_interest": "OTHER", "final_rating": "REVIEW"},
                            tmp_path, ref, ResearchPolicy())
    assert result["status"] == "blocked"
    assert {"missing_verified_prices", "identity_mismatch", "mandate_mismatch",
            "unparsed_rating", "missing_decision"} <= {i["code"] for i in result["issues"]}
