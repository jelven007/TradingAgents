"""Deterministic reading aids for verified reports; never generates investment claims."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradingagents.application.securities import security
from tradingagents.domain.research import canonical_symbol
from tradingagents.infrastructure.artifacts import read_verified

# Names are navigation metadata, not vendor-supplied company or market facts.
NAMES = {
    "NVDA": ("英伟达", "NVIDIA"), "AAPL": ("苹果", "Apple"),
    "MSFT": ("微软", "Microsoft"), "GOOGL": ("谷歌", "Alphabet"),
    "AMZN": ("亚马逊", "Amazon"), "TSLA": ("特斯拉", "Tesla"),
    "META": ("Meta", "Facebook"), "SPY": ("标普500 ETF", "SPDR S&P 500"),
    "QQQ": ("纳斯达克100 ETF", "Invesco QQQ"), "BTC-USD": ("比特币", "Bitcoin"),
}
RATINGS = {
    "Buy": "研究观点偏积极；需要结合原文依据、估值和风险理解。",
    "Overweight": "研究观点倾向在本次期限内强于对照基准；不是增加仓位的指令。",
    "Hold": "研究观点倾向维持观察；不代表价格稳定或没有风险。",
    "Underweight": "研究观点倾向在本次期限内弱于对照基准；不是减仓指令。",
    "Sell": "研究观点偏消极；需要核验负面依据及结论失效条件。",
}


def instrument(symbol):
    listed = security(symbol)
    if listed:
        return {**listed, "name_source": "系统预置证券目录"}
    names = NAMES.get(symbol)
    return {"symbol": symbol, "name": names[0] if names else symbol,
            "aliases": list(names or ()), "name_source": "系统预置" if names else "代码输入"}


class WatchlistInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["add", "remove", "save_note"]
    symbol: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=4000)

    @field_validator("symbol")
    @classmethod
    def normalize(cls, value):
        return canonical_symbol(value)


def report_brief(path, manifest, mandate, quality):
    state = json.loads((path / "state.json").read_bytes())
    evidence = json.loads((path / "evidence" / "manifest.json").read_bytes())
    synthetic = manifest.get("settings", {}).get("demo_mode") is True
    records = {r["content_sha256"]: r for r in evidence["records"]}
    codes = {i["code"] for i in quality["issues"]}
    price = None
    candidates = []
    for calc in quality["calculations"]:
        if calc.get("check") != "OHLCV":
            continue
        ref = calc["evidence_sha256"]
        record = records.get(ref)
        if not record or record["status"] == "error":
            continue
        fact = json.loads(read_verified(path / "evidence" / "blobs" / f"{ref}.json", ref))
        synthetic = synthetic or fact.get("synthetic") is True
        if (fact.get("currency") == mandate["quote_currency"]
                and fact.get("ticker") == mandate["ticker"]
                and fact.get("as_of_date") == mandate["analysis_date"]):
            candidates.append({**calc, "currency": fact["currency"], "source": record["source"],
                               "synthetic": fact.get("synthetic") is True})
    unsafe = {"future_price", "stale_price", "unverified_currency", "currency_mismatch",
              "invalid_market_facts", "conflicting_prices", "missing_verified_prices"}
    if candidates and not unsafe.intersection(codes):
        price = max(candidates, key=lambda c: c["price_date"])
    debate = state.get("investment_debate_state")
    debate = debate if isinstance(debate, dict) else {}
    risk = state.get("risk_debate_state")
    risk = risk if isinstance(risk, dict) else {}
    display = state.get("display_currency") or mandate["quote_currency"]
    converted = None
    # Read FX from the captured blob, not arbitrary prose or unbound state values.
    if price and display != price["currency"]:
        for record in evidence["records"]:
            if record["method"] != "display_fx" or record["status"] == "error":
                continue
            ref = record["content_sha256"]
            fact = json.loads(read_verified(path / "evidence" / "blobs" / f"{ref}.json", ref))
            try:
                age = (date.fromisoformat(mandate["analysis_date"]) - date.fromisoformat(fact["price_date"])).days
                rate = Decimal(str(fact["values"]["Close"]))
                if (fact["ticker"] == f"{price['currency']}{display}=X"
                        and fact["currency"] == display and rate.is_finite() and rate > 0
                        and 0 <= age <= 7):
                    converted = {"close": str((Decimal(price["close"]) * rate).quantize(Decimal("0.01"))),
                                 "currency": display, "rate": str(rate),
                                 "rate_date": fact["price_date"], "source": record["source"]}
            except (KeyError, TypeError, ValueError):
                continue

    def excerpt(title, source, value):
        text = value.strip() if isinstance(value, str) else ""
        return {"title": title, "source": source, "text": text[:1600],
                "truncated": len(text) > 1600, "provided": bool(text)}

    return {
        "instrument": instrument(mandate["ticker"]), "synthetic": synthetic,
        "rating_meaning": RATINGS.get(manifest["rating"], "未能确认研究观点，请查看质量问题。"),
        "price": price,
        "display_currency": display, "converted_price": converted,
        "research_status": state.get("research_status", "legacy"),
        "decision": state.get("decision"), "data_gaps": state.get("data_gaps", []),
        "excerpts": [
            excerpt("研究结论", "state.final_trade_decision", state.get("final_trade_decision")),
            excerpt("判断理由", "state.investment_plan", state.get("investment_plan")),
            excerpt("支持观点", "state.investment_debate_state.bull_history", debate.get("bull_history")),
            excerpt("反方观点", "state.investment_debate_state.bear_history", debate.get("bear_history")),
            excerpt("风险讨论", "state.risk_debate_state.history", risk.get("history")),
        ],
        "evidence_count": len(evidence["records"]),
        "publication_times_known": all(r.get("known_at") for r in evidence["records"])
        if evidence["records"] else False,
        "source": "已通过文件完整性核验的固定报告；原文节选，无新增模型调用",
    }
