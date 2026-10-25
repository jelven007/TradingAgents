"""Real, dated Yahoo adapters for the bounded stock route."""

from datetime import UTC, date, datetime, timedelta


def history_facts(ticker, analysis_date, quote_currency):
    import yfinance as yf
    end = date.fromisoformat(analysis_date) + timedelta(days=1)
    item = yf.Ticker(ticker)
    frame = item.history(start=str(end - timedelta(days=120)), end=str(end),
                         auto_adjust=False, timeout=12, raise_errors=True)
    if frame.empty:
        raise ValueError("no daily prices")
    rows = []
    for index, row in frame.iterrows():
        day = index.date().isoformat()
        if day <= analysis_date:
            rows.append({"date": day, **{k: float(row[k]) for k in
                                        ("Open", "High", "Low", "Close", "Volume")}})
    if not rows:
        raise ValueError("no dated prices")
    last = rows[-1]
    return {"ticker": ticker, "as_of_date": analysis_date, "price_date": last["date"],
            "currency": item.history_metadata.get("currency"),
            "values": {k: last[k] for k in ("Open", "High", "Low", "Close", "Volume")},
            "history": rows, "expected_currency": quote_currency, "auto_adjust": False}


def company_data(ticker, analysis_date):
    import yfinance as yf
    if analysis_date != datetime.now(UTC).date().isoformat():
        return {"unavailable": "historical company/news snapshot not certified"}
    info = yf.Ticker(ticker).get_info()
    fields = ("longName", "sector", "industry", "longBusinessSummary", "currency",
              "marketCap", "trailingPE", "forwardPE", "priceToBook", "totalRevenue",
              "revenueGrowth", "earningsGrowth", "profitMargins", "totalCash",
              "totalDebt", "freeCashflow")
    return {key: info[key] for key in fields if key in info and info[key] is not None}


def news_data(ticker, analysis_date):
    import yfinance as yf
    if analysis_date != datetime.now(UTC).date().isoformat():
        return {"unavailable": "historical news snapshot not certified"}
    news = yf.Ticker(ticker).get_news(count=6)
    rows = []
    for item in news:
        content = item.get("content") or item
        published = content.get("pubDate")
        if published and published[:10] <= analysis_date:
            rows.append({k: content.get(k) for k in ("title", "summary", "pubDate",
                                                     "provider", "canonicalUrl")})
    return {"items": rows, "note": "news retrieval time does not certify first publication"}
