#!/usr/bin/env python3
"""
score_universe.py — Score SOP watchlist tickers against the three strategies.

Usage:
    python3 scripts/score_universe.py [--json-dir DIR] [--quotes-json FILE] [--output TABLE|CSV|JSON]

Inputs:
    Historical data files: JSON files from the Robinhood MCP get_equity_historicals tool.
      Each file has schema: {data: {results: [{symbol, bars: [{begins_at, open_price,
      close_price, high_price, low_price, volume, session}]}]}}
    Quotes data (optional): JSON file with bid/ask prices per ticker for spread filtering.
      Schema: {TICKER: {bid: float, ask: float}}

Outputs (default: TABLE to stdout):
    Scored table with columns: SYM, CLOSE, SMA20, SMA50, RSI14, T, B, R, TIER, SIGNAL, SPREAD

Strategies (references/strategy.md §A):
    A.1 Trend-following:  close > SMA20 > SMA50; score 60 base, +15 SMA20 rising, +15 near 52wk high, -20 overextended
    A.2 Momentum/breakout: close >= prior_20d_high AND vol >= 1.5x avg; score 65 base, bonuses/penalties
    A.3 RSI mean-reversion: RSI14 <= 35 AND close > SMA50; score 55 base, bonuses
    Confluence: >=2 strategies fire → upgrade one tier (capped at high)
    Spread filter: (ask-bid)/mid > 50 bps → flag WIDE (still shown, not tradeable)
"""
import argparse
import csv
import json
import os
import sys


# ---------------------------------------------------------------------------
# Strategy scoring functions (strategy.md §A)
# ---------------------------------------------------------------------------

def sma(prices: list[float], n: int) -> float | None:
    if len(prices) < n:
        return None
    return sum(prices[-n:]) / n


def rsi14(closes: list[float], period: int = 14) -> float | None:
    # Needs at least period+1 data points for one RSI value
    if len(closes) < period + 1:
        return None
    # Use the last (period+1) closes for a simple (non-Wilder-smoothed) RSI
    c = closes[-(period + 1):]
    gains, losses = [], []
    for i in range(1, len(c)):
        delta = c[i] - c[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def score_trend(close, sma20, sma50, sma20_5ago, high_52w):
    """A.1 Trend-following. Returns (score, fires: bool)."""
    if None in (close, sma20, sma50):
        return 0, False
    if not (close > sma20 > sma50):
        return 0, False
    score = 60
    if sma20_5ago is not None and sma20 > sma20_5ago:
        score += 15
    if high_52w is not None and close >= high_52w * 0.96:
        score += 15
    if close > sma20 * 1.12:
        score -= 20
    score = max(0, min(100, score))
    return score, score >= 45


def score_breakout(close, prior_20d_high, today_vol, avg_20d_vol):
    """A.2 Momentum/breakout. Returns (score, fires: bool)."""
    if None in (close, prior_20d_high, today_vol, avg_20d_vol) or avg_20d_vol == 0:
        return 0, False
    if not (close >= prior_20d_high and today_vol >= 1.5 * avg_20d_vol):
        return 0, False
    score = 65
    if today_vol >= 2 * avg_20d_vol:
        score += 15
    pct_above = (close - prior_20d_high) / prior_20d_high
    if pct_above < 0.03:
        score += 10
    if pct_above > 0.08:
        score -= 15
    score = max(0, min(100, score))
    return score, score >= 50


def score_rsi_revert(rsi_val, close, sma50):
    """A.3 RSI mean-reversion. Returns (score, fires: bool)."""
    if None in (rsi_val, close, sma50):
        return 0, False
    if not (rsi_val <= 35 and close > sma50):
        return 0, False
    score = 55
    if rsi_val <= 25:
        score += 20
    if sma50 > 0 and abs(close - sma50) / sma50 <= 0.03:
        score += 15
    score = max(0, min(100, score))
    return score, score >= 45


def tier_from_score(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 65:
        return "medium"
    if score >= 45:
        return "low"
    return "skip"


_TIER_RANK = {"skip": 0, "low": 1, "medium": 2, "high": 3}


def confluence_upgrade(base_tier: str) -> str:
    """Upgrade one tier level, capped at 'high'."""
    rank = _TIER_RANK.get(base_tier, 0)
    upgraded = min(rank + 1, 3)
    return list(_TIER_RANK.keys())[upgraded]


def spread_flag(bid: float, ask: float) -> str:
    """Return 'OK' or 'WIDE'. Empty string when bid/ask unavailable."""
    if not bid or not ask:
        return "?"
    mid = (bid + ask) / 2.0
    return "WIDE" if (ask - bid) / mid > 0.005 else "OK"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_historical_files(directory: str) -> dict[str, list[dict]]:
    """Load all JSON historical files from a directory. Returns {symbol: [bars]}."""
    all_bars: dict[str, list[dict]] = {}
    if not os.path.isdir(directory):
        print(f"[WARN] historical dir not found: {directory}", file=sys.stderr)
        return all_bars
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json") and not fname.endswith(".txt"):
            continue
        fpath = os.path.join(directory, fname)
        try:
            with open(fpath) as f:
                data = json.load(f)
            if "data" not in data or "results" not in data["data"]:
                continue  # not a historicals file (e.g. quotes fixture)
            results = data["data"]["results"]
            for r in results:
                sym = r.get("symbol", "")
                bars_raw = r.get("bars", [])
                bars = []
                for b in bars_raw:
                    try:
                        bars.append({
                            "c": float(b["close_price"]),
                            "h": float(b["high_price"]),
                            "l": float(b["low_price"]),
                            "v": float(b["volume"]),
                        })
                    except (KeyError, ValueError, TypeError):
                        pass
                if sym and bars:
                    all_bars[sym] = bars
        except Exception as exc:
            print(f"[WARN] failed to load {fname}: {exc}", file=sys.stderr)
    return all_bars


def load_quotes(quotes_file: str) -> dict[str, dict]:
    """Load optional quotes JSON: {TICKER: {bid, ask}}."""
    if not quotes_file or not os.path.isfile(quotes_file):
        return {}
    with open(quotes_file) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_ticker(sym: str, bars: list[dict], quote: dict) -> dict:
    """Score one ticker. Returns a result row dict."""
    n = len(bars)
    row: dict = {"sym": sym, "n_bars": n}

    if n < 51:
        row["skip_reason"] = f"only {n} bars (need ≥51)"
        return row

    closes = [b["c"] for b in bars]
    highs  = [b["h"] for b in bars]
    vols   = [b["v"] for b in bars]

    close = closes[-1]
    s20 = sma(closes, 20)
    s50 = sma(closes, 50)
    s20_5ago = sma(closes[:-5], 20) if n >= 25 else None
    h52 = max(highs[-252:])
    prior_20d_high = max(highs[-21:-1]) if n >= 21 else None
    today_vol = vols[-1]
    avg_vol_20 = sum(vols[-21:-1]) / 20 if n >= 21 else None
    rsi = rsi14(closes)

    t_score, t_fire = score_trend(close, s20, s50, s20_5ago, h52)
    b_score, b_fire = score_breakout(close, prior_20d_high, today_vol, avg_vol_20)
    r_score, r_fire = score_rsi_revert(rsi, close, s50)

    fires = []
    if t_fire:
        fires.append(("trend", t_score))
    if b_fire:
        fires.append(("breakout", b_score))
    if r_fire:
        fires.append(("rsi_revert", r_score))

    best_score = max(s for _, s in fires) if fires else 0
    best_tier = tier_from_score(best_score)
    if len(fires) >= 2:
        best_tier = confluence_upgrade(best_tier)
    signal_src = "+".join(name for name, _ in fires) if fires else "—"

    bid = quote.get("bid", 0.0)
    ask = quote.get("ask", 0.0)

    row.update({
        "close": close,
        "sma20": round(s20, 2) if s20 is not None else None,
        "sma50": round(s50, 2) if s50 is not None else None,
        "rsi14": round(rsi, 1) if rsi is not None else None,
        "h52": round(h52, 2),
        "t_score": t_score,
        "b_score": b_score,
        "r_score": r_score,
        "fires": fires,
        "tier": best_tier,
        "signal": signal_src,
        "bid": bid,
        "ask": ask,
        "spread": spread_flag(bid, ask),
    })
    return row


def score_all(all_bars: dict, quotes: dict) -> list[dict]:
    rows = []
    for sym in sorted(all_bars):
        row = score_ticker(sym, all_bars[sym], quotes.get(sym, {}))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

_TIER_SORT = {"high": 0, "medium": 1, "low": 2, "skip": 3}


def sort_rows(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (candidates, no_fire, skipped_insufficient)."""
    cands = [r for r in rows if r.get("fires")]
    no_fire = [r for r in rows if not r.get("fires") and "skip_reason" not in r]
    insufficient = [r for r in rows if "skip_reason" in r]
    cands.sort(key=lambda r: (_TIER_SORT.get(r["tier"], 3), -r.get("t_score", 0) - r.get("b_score", 0) - r.get("r_score", 0)))
    return cands, no_fire, insufficient


def print_table(rows: list[dict]) -> None:
    cands, no_fire, insuf = sort_rows(rows)
    header = f"{'SYM':<6} {'CLOSE':>8} {'SMA20':>8} {'SMA50':>8} {'RSI14':>6} {'T':>4} {'B':>4} {'R':>4} {'TIER':<8} {'SIGNAL':<22} SPREAD"
    print(header)
    print("-" * len(header))
    for r in cands:
        sp = r.get("spread", "?")
        sp_flag = f" !{sp}" if sp != "OK" else ""
        print(
            f"{r['sym']:<6} {r.get('close', 0):>8.2f} {str(r.get('sma20', '')):>8} "
            f"{str(r.get('sma50', '')):>8} {str(r.get('rsi14', '')):>6} "
            f"{r.get('t_score', 0):>4} {r.get('b_score', 0):>4} {r.get('r_score', 0):>4} "
            f"{r.get('tier', ''):<8} {r.get('signal', ''):<22}{sp_flag}"
        )
    if no_fire:
        print(f"\nNo-fire ({len(no_fire)}): {', '.join(r['sym'] for r in no_fire)}")
    if insuf:
        print(f"Insufficient data: {', '.join(r['sym'] + '(' + r['skip_reason'] + ')' for r in insuf)}")


def print_csv(rows: list[dict]) -> None:
    cands, no_fire, _ = sort_rows(rows)
    all_scored = cands + no_fire
    fields = ["sym", "close", "sma20", "sma50", "rsi14", "t_score", "b_score", "r_score", "tier", "signal", "spread"]
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(all_scored)


def print_json(rows: list[dict]) -> None:
    # Strip non-serialisable fields
    out = []
    for r in rows:
        row = {k: v for k, v in r.items() if k != "fires"}
        if "fires" in r:
            row["fires"] = [f"{n}:{s}" for n, s in r["fires"]]
        out.append(row)
    print(json.dumps(out, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Score SOP watchlist against strategy.md §A")
    parser.add_argument("--json-dir", default=".", help="Directory containing historical JSON files from the MCP")
    parser.add_argument("--quotes-json", default="", help="Optional JSON file with {TICKER:{bid,ask}} for spread filtering")
    parser.add_argument("--output", choices=["TABLE", "CSV", "JSON"], default="TABLE")
    args = parser.parse_args()

    all_bars = load_historical_files(args.json_dir)
    if not all_bars:
        print("No historical data loaded. Pass --json-dir pointing at MCP result files.", file=sys.stderr)
        sys.exit(1)

    quotes = load_quotes(args.quotes_json) if args.quotes_json else {}
    rows = score_all(all_bars, quotes)

    if args.output == "CSV":
        print_csv(rows)
    elif args.output == "JSON":
        print_json(rows)
    else:
        print_table(rows)


if __name__ == "__main__":
    main()
