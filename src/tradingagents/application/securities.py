"""Dated, packaged selection metadata. No quotes or implicit workspace grants."""

import json
from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def catalog():
    data = json.loads(files("tradingagents").joinpath("assets/security-catalog.json").read_bytes())
    rows = {item["symbol"]: item for item in data["instruments"]}
    return {key: value for key, value in data.items() if key != "instruments"}, rows


def security(symbol):
    row = catalog()[1].get(symbol.upper())
    return dict(row) if row else None


def search(*, query="", market="", allowed=None, limit=24, offset=0):
    if market not in {"", "US", "CN", "HK"} or len(query) > 100:
        raise ValueError("invalid instrument search")
    if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
        raise ValueError("invalid pagination")
    needle = query.strip().casefold()
    rows = [row for row in catalog()[1].values()
            if (allowed is None or row["symbol"] in allowed)
            and (not market or row["market"] == market)
            and (not needle or needle in " ".join(
                [row["symbol"], row["name"], *row["aliases"]]).casefold())]
    popular = {"NVDA": 0, "AAPL": 1, "MSFT": 2, "TSLA": 3,
               "600519.SS": 4, "000001.SZ": 5, "0700.HK": 6, "9988.HK": 7}
    rows.sort(key=lambda row: (row["symbol"] != query.upper(),
                              popular.get(row["symbol"], 100), row["symbol"]))
    return {"items": [dict(row) for row in rows[offset:offset + limit]],
            "total": len(rows), "limit": limit, "offset": offset}
