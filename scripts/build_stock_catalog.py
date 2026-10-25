"""Build a complete, dated local selection catalog; do not bundle quote values."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SINA = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
SOURCES = {
    "nasdaq": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other_us": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9._^=+-]{0,31}$")
POPULAR = {
    "NVDA": ("英伟达", "NVIDIA"), "AAPL": ("苹果", "Apple"),
    "MSFT": ("微软", "Microsoft"), "GOOGL": ("谷歌", "Alphabet"),
    "AMZN": ("亚马逊", "Amazon"), "TSLA": ("特斯拉", "Tesla"),
    "META": ("Meta", "Facebook"), "SPY": ("标普500 ETF", "SPDR S&P 500"),
    "QQQ": ("纳斯达克100 ETF", "Invesco QQQ"), "BRK-B": ("伯克希尔B", "Berkshire"),
}


def get(session, url, **params):
    response = session.get(url, params=params, timeout=(8, 20))
    response.raise_for_status()
    return response


def sina(session, market, cache):
    is_hk = market == "HK"
    node = "qbgg_hk" if is_hk else "hs_a"
    method = "getHKStockData" if is_hk else "getHQNodeData"
    count_method = "getHKStockCount" if is_hk else "getHQNodeStockCount"
    count_response = get(session, SINA + "Market_Center." + count_method, node=node)
    count = int(re.search(r"\d+", count_response.text)[0])
    size = 60 if is_hk else 80
    rows = []
    # Sina's HK count endpoint excludes some classes returned by its list.
    # Verify the list's terminal empty page, with a hard bound, instead of
    # stopping at that smaller estimate.
    pages = 100 if is_hk else math.ceil(count / size)
    terminal_page = None
    for page in range(1, pages + 1):
        target = cache / f"sina-{market}-{page}.json"
        if target.exists():
            batch = json.loads(target.read_text())
        else:
            batch = get(session, SINA + "Market_Center." + method,
                        page=page, num=size, sort="symbol", asc=1, node=node).json()
            if not isinstance(batch, list) or not batch and not is_hk:
                raise ValueError(f"{market}: missing page {page}; refusing an incomplete catalog")
            target.write_text(json.dumps(batch, ensure_ascii=False))
        if is_hk and not batch:
            terminal_page = page
            break
        rows.extend(batch)
        if page == 1 or page % 10 == 0 or page == pages:
            print(json.dumps({"market": market, "page": page, "pages": pages,
                              "rows": len(rows), "expected": count}), flush=True)
    if (not is_hk and len(rows) != count
            or len({row["symbol"] for row in rows}) != len(rows)
            or is_hk and terminal_page is None):
        raise ValueError(f"{market}: listing count changed; refresh cached pages before retrying")
    return rows, {"source": "新浪财经证券目录", "url": SINA + "Market_Center." + method,
                  "reported_count": count, "downloaded_count": len(rows), "market": market,
                  "terminal_page": terminal_page,
                  "completeness": "terminal empty page" if is_hk else "exact source count"}


def us(session, cache):
    entries, sources = [], []
    for key, url in SOURCES.items():
        target = cache / f"{key}.txt"
        if target.exists():
            text = target.read_text()
        else:
            text = get(session, url).text
            target.write_text(text)
        lines = text.splitlines()
        if not lines or not lines[-1].startswith("File Creation Time:"):
            raise ValueError(f"{key}: missing completeness trailer")
        rows = list(csv.DictReader(io.StringIO("\n".join(lines[:-1])), delimiter="|"))
        for row in rows:
            if row.get("Test Issue") != "N":
                continue
            symbol = row.get("Symbol") or row.get("ACT Symbol") or ""
            # Yahoo uses a dash for US share classes. Preferred symbols with '$'
            # or listing-only punctuation are kept out of the ordinary-stock UI.
            symbol = symbol.replace(".", "-")
            if not SYMBOL.fullmatch(symbol):
                continue
            name = row["Security Name"].strip()
            popular = POPULAR.get(symbol)
            exchange = "NASDAQ" if key == "nasdaq" else {
                "A": "NYSE American", "N": "NYSE", "P": "NYSE Arca",
                "Z": "Cboe", "V": "IEX",
            }.get(row.get("Exchange"), row.get("Exchange", "US"))
            entries.append({"symbol": symbol, "name": popular[0] if popular else name,
                            "aliases": list(dict.fromkeys([name, *(popular or ())])),
                            "market": "US", "exchange": exchange, "quote_currency": "USD",
                            "benchmark": "SPY", "asset_type": "stock",
                            "kind": "etf" if row.get("ETF") == "Y" else "stock",
                            "source": "NASDAQ Trader"})
        sources.append({"source": "NASDAQ Trader", "url": url, "listing_time": lines[-1].split("|")[0],
                        "reported_count": len(rows), "sha256": hashlib.sha256(text.encode()).hexdigest()})
    return entries, sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/stock-catalog-sources")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "src/tradingagents/assets/security-catalog.json")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
    records, sources = us(session, args.cache)
    for market in ("CN", "HK"):
        rows, source = sina(session, market, args.cache)
        sources.append(source)
        for row in rows:
            code = row["symbol"]
            if market == "CN":
                exchange = {"sh": "上海证券交易所", "sz": "深圳证券交易所",
                            "bj": "北京证券交易所"}[code[:2]]
                symbol = code[2:] + {"sh": ".SS", "sz": ".SZ", "bj": ".BJ"}[code[:2]]
            else:
                exchange = "香港交易所"
                symbol = f"{int(code):04d}.HK"
            if not SYMBOL.fullmatch(symbol):
                raise ValueError(f"Invalid symbol from listing source: {symbol}")
            records.append({"symbol": symbol, "name": row["name"],
                            "aliases": list(dict.fromkeys([row.get("engname") or row["name"], code,
                                                          code[2:] if market == "CN" else code])),
                            "market": market, "exchange": exchange,
                            "quote_currency": "CNY" if market == "CN"
                            or 80000 <= int(code) < 90000 else "HKD",
                            "benchmark": "000300.SS" if market == "CN" else "^HSI",
                            "asset_type": "stock", "kind": "stock", "source": "新浪财经证券目录"})
    unique = {row["symbol"]: row for row in records}
    counts = {market: sum(row["market"] == market for row in unique.values())
              for market in ("US", "CN", "HK")}
    if counts["US"] < 5000 or counts["CN"] < 5000 or counts["HK"] < 1500:
        raise ValueError(f"Incomplete market coverage: {counts}")
    document = {
        "schema_version": 1, "generated_at": datetime.now(UTC).isoformat(),
        "coverage": "来源目录中的美股上市证券、沪深北A股、港股；不是全球证券或实时行情终端。",
        "excluded": "NASDAQ测试证券、无法映射的特殊证券代码；名称目录不保证仍可交易或行情可获取。",
        "counts": counts, "sources": sources,
        "instruments": sorted(unique.values(), key=lambda row: (row["market"], row["symbol"])),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    print(json.dumps({"output": str(args.out), "counts": counts, "total": len(unique),
                      "quote_values_bundled": False}), flush=True)


if __name__ == "__main__":
    main()
