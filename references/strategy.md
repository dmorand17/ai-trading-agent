# Trading Strategy & Rules

The single authoritative reference for **what to buy, how to size it, when to exit, and the
mandatory log schemas.** This file replaces the old signal-by-signal split — the trade ideas
now come from a small set of classic, price-based strategies (§A), not from external cluster
feeds.

Everything here is tunable **except §0**. `mode.toml` and `watchlist.json` are the runtime
sources of truth for execution mode and the trading universe; this file is the source of truth
for strategy and sizing.

---

## 0. Non-negotiable rules (these always win)

If anything below conflicts with §0, **§0 wins**. Bright-line invariants.

### 0.1 Position cap: 5% per single position (overridable per-symbol via watchlist)

- **Default cap: 5% of total portfolio value per single ticker.** Exposure =
  `(open_qty × current_mark) / total_equity`. Includes pre-existing holdings.
- **Per-symbol override:** if the ticker is in `watchlist.json` with `max_allocation_pct`, that
  value **replaces** the 5% default for that ticker.
- **Cash reserve interacts:** even with a higher per-symbol cap, total deployed capital still
  respects `cash_reserve_pct` (§2.3) — you cannot push cash below the reserve floor.
- The invariant: there is *always* an enforced per-position cap and a cash-reserve floor. The
  SOP may never trade past them.

### 0.2 Order type: limit only, within 0.2% of ask

- Never `market`. Never `stop_market`. Never `market-on-close`.
- Entry limit = `current_ask × 1.002`. Exit limit = `current_bid × 0.998`.
- If the spread is so wide that `current_ask × 1.002` is still inside the spread, skip the
  trade — the book is too thin.

### 0.3 Hard stop: −8% from entry, close without waiting

- For every open position, compute `(current_mark − entry_price) / entry_price` on every loop.
- If ≤ `−0.08`, submit a closing limit at `current_bid × 0.998` **immediately**.
- No averaging down, no "wait for the bounce," no overriding by strategy score.
- Independent of, and tighter than, the trailing stop (§4.3).

### 0.4 Journal mandatory every day, even on no-trade days

- A human-readable `journal/{YYYY-MM-DD}.md` must be created/updated on every SOP invocation,
  **whether or not any orders were placed**. Template in §7.
- On a no-trade day, write `None today.` under Trades Executed and still complete the other
  sections. The reflection records *why* nothing fired — that's the tuning data.

### 0.5 Never trade when the market is closed

- Before any order tool fires, confirm the US regular session is open.
- Source of truth: (1) Robinhood MCP market-status read; (2) calendar fallback Mon–Fri
  09:30–16:00 America/New_York, excluding NYSE holidays.
- If closed → signal scans and journal entries continue; **no orders**, including exits. A
  hard-stop exit (§0.3) that fires after close is queued for the next open and logged.

---

## A. Strategy set (how candidates are generated)

The SOP evaluates each watchlist ticker against three classic, price-based strategies. Each
strategy independently emits a **signal** (`fire` / `no`) and a **score** (0–100). Inputs are
daily OHLCV and quotes pulled from the Robinhood MCP (or a brief web/quote read as fallback).

A ticker becomes a **candidate** when at least one strategy fires. Its conviction tier comes
from the best firing strategy's score (§3.1), with a confluence upgrade when more than one
fires (§5).

### A.1 Trend-following (the baseline strategy)

Buy strength that is already trending; let the trend carry it.

- **Inputs:** 20-day SMA, 50-day SMA, latest close.
- **Fires when:** `close > SMA20 > SMA50` (constructive uptrend, fast above slow).
- **Score:**
  - Base 60 when the fire condition holds.
  - `+15` if `SMA20` is rising vs 5 trading days ago.
  - `+15` if `close` is within 4% of the 52-week high (trending toward new highs, not extended).
  - `−20` if `close` is more than 12% above `SMA20` (overextended — chasing).
  - Clamp to 0–100. Below 45 → treat as `no`.
- **Disqualifier:** if `close < SMA20` AND `close < SMA50`, this strategy does not fire.

### A.2 Momentum / breakout

Buy a clean breakout above a recent base on expanding volume.

- **Inputs:** prior 20-day high (excluding today), latest close, today's volume, 20-day average
  volume.
- **Fires when:** `close >= prior_20d_high` (new 20-day high) AND
  `today_volume >= 1.5 × avg_20d_volume` (volume confirmation).
- **Score:**
  - Base 65 when the fire condition holds.
  - `+15` if `today_volume >= 2 × avg_20d_volume` (strong confirmation).
  - `+10` if the breakout clears the prior high by < 3% (early, not extended).
  - `−15` if the close is > 8% above the prior 20-day high (chasing a gap).
  - Clamp to 0–100. Below 50 → treat as `no`.

### A.3 RSI mean-reversion

Buy a temporary oversold dip *within* an established uptrend — never a falling knife.

- **Inputs:** 14-day RSI, 50-day SMA, latest close.
- **Fires when:** `RSI14 <= 35` (oversold) AND `close > SMA50` (still in a longer uptrend).
- **Score:**
  - Base 55 when the fire condition holds.
  - `+20` if `RSI14 <= 25` (deeper oversold).
  - `+15` if `close` is within 3% of `SMA50` (pullback to support, not a collapse).
  - `−25` if `close < SMA50` (no uptrend → do not fire; enforced by the fire condition).
  - Clamp to 0–100. Below 45 → treat as `no`.
- **Caution:** mean-reversion entries get a tighter watch — the −8% hard stop (§0.3) is the
  backstop if the "dip" keeps falling.

### A.4 Tuning knobs

The thresholds above are the defaults. Tune them here as the paper track record accumulates;
the weekly review (`.claude/skills/weekly-review`) suggests changes.

```toml
[trend_following]
min_score_to_trade = 45
overextension_pct  = 0.12   # close this far above SMA20 → penalize

[momentum_breakout]
min_score_to_trade   = 50
breakout_lookback    = 20    # trading days
volume_confirm_mult  = 1.5   # today_volume ≥ this × avg_20d_volume

[rsi_mean_reversion]
min_score_to_trade = 45
rsi_oversold       = 35
rsi_deep_oversold  = 25
rsi_period         = 14
```

---

## 1. Mode handling (paper → live transition)

The SOP reads `mode.toml` at repo root **on every invocation, before any order tool is
touched.** If the file is missing, create it with paper defaults and report to the user.

### 1.1 `mode.toml` schema

```toml
mode = "paper"                  # "paper" | "live"
live_allowlist = []             # [] = all eligible in live; ["AAPL"] = only AAPL goes live
require_manual_confirm = true   # pause for explicit "yes" before each live order
block_tickers = []              # global blocklist, overrides everything
daily_loss_cap_pct = 0.02       # halt new entries when day P&L ≤ −this × equity
require_risk_review = true       # spawn the risk-reviewer subagent before each order
```

### 1.2 Paper mode (default)

- All strategy scans and pre-trade review blocks run normally.
- **No MCP order tool is invoked.**
- `trade-log.jsonl` entries are appended with `mode: "paper"` and `result: "paper"`.

### 1.3 Live mode

Pre-flight on every order: `tools/list` returns Robinhood order tools; the MCP account ID
matches the user-confirmed **Agentic** account (never the primary individual account); ticker is
in `live_allowlist` (or it's empty); ticker not in `block_tickers`; risk caps (§3) not breached;
no `KILL_SWITCH`; `trade-log.jsonl` writable. If `require_manual_confirm = true`, prompt and
wait for explicit `yes`.

### 1.4 Staged transition

Paper ≥ 30 trading days → live + manual-confirm + 1–3 allowlisted tickers ≥ 2 weeks → widen
allowlist → open allowlist → finally `require_manual_confirm = false`. Rollback is always: edit
`mode.toml`, save, next invocation honors it.

---

## 2. Watchlist & cash reserve (`watchlist.json`)

Required config at repo root, read on every invocation. The SOP **never** writes to it.

### 2.1 Schema

```json
{
  "watchlist": [
    { "symbol": "SPY", "description": "S&P 500 ETF — baseline market exposure", "max_allocation_pct": 15 }
  ],
  "cash_reserve_pct": 20
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `watchlist` | yes | Permitted symbols. Empty array = no symbol restriction. |
| `watchlist[].symbol` | yes | Uppercase US-listed ticker. |
| `watchlist[].description` | yes | Free text; surfaced in the journal so future-you remembers the thesis. |
| `watchlist[].max_allocation_pct` | yes | Per-symbol cap as % of equity (0–100). Replaces the 5% default in §0.1. |
| `cash_reserve_pct` | yes | Minimum cash to hold as % of equity. The SOP may never deploy past `(100 − cash_reserve_pct)%`. |

### 2.2 Universe filter

- **Populated watchlist:** no order for an off-watchlist ticker. Off-watchlist names that score
  are still logged in Market Research with `Decision: Skipped — not on watchlist`. Recommended
  for live.
- **Empty watchlist (`[]`):** no symbol restriction. Useful for paper-mode discovery.

### 2.3 Cash reserve

- Compute `deployed_pct = (total_equity − cash_balance) / total_equity` each loop.
- A new buy may not push `deployed_pct` above `(100 − cash_reserve_pct) / 100`.
- Example: `equity = $20,000`, `cash_reserve_pct = 20` → deploy ≤ $16,000, keep ≥ $4,000 cash.
  If a candidate buy would breach the floor, reduce `qty` to fit; never below the §3.1 minimum.

### 2.4 Per-symbol cap precedence

1. `watchlist[].max_allocation_pct` if the symbol is in the watchlist, else
2. the 5% default from §0.1.

Some cap is **always** enforced. The SOP may never compute "no cap applies."

### 2.5 Watchlist edits

The SOP never writes `watchlist.json`. If a strong candidate is off-watchlist, log it and
suggest the edit in the End-of-Day Reflection — the user decides.

---

## 3. Position sizing & risk caps

Driven by the conviction tier from §A scoring.

### 3.1 Tier → target size

| Tier | Score | Position size (% of equity) |
| --- | --- | --- |
| skip | < min_score_to_trade | 0% (no trade) |
| low | min–64 | 0.5% |
| medium | 65–79 | 1.0% |
| high | 80–100 | 2.0% |

`qty = floor((equity × tier_pct) / limit_price)`, then **clamp downward** to satisfy the
per-symbol cap (§2.4) and the cash-reserve floor (§2.3). If clamping drops `qty` below 1 share,
skip and log `Decision: Skipped — sizing collapsed to zero (reserve or per-symbol cap)`.

### 3.2 Hard caps

- **Per-ticker:** total exposure ≤ the §2.4 cap. A new buy may not push past.
- **Cash-reserve floor:** total deployed ≤ `(1 − cash_reserve_pct / 100) × equity` (§2.3).
- **Daily loss cap:** if realized + unrealized day P&L ≤ `−daily_loss_cap_pct × equity` (default
  −2%), halt new entries for 24h. Existing positions and their exits keep running.

### 3.3 Liquidity floor

Skip any ticker with 20-day average daily dollar volume < $5M.

---

## 4. Entry & exit rules

### 4.1 Entry

- **Limit only**, `last_quote × 1.002` (20 bps slippage budget).
- **Spread filter:** skip when `(ask − bid) / mid` exceeds **50 bps**.
- **Time-in-force:** day order. Re-evaluate next session if not filled.
- **One entry per signal:** do not split into child orders.

### 4.2 Exits (this is how positions close — strategies never produce sells)

Two stops are always in flight. Whichever fires first wins.

| Exit reason | Trigger | Action |
| --- | --- | --- |
| Hard stop | −8% from entry (§0.3) | close 100% at `bid × 0.998`, no waiting |
| Trailing stop | drawdown from peak ≥ tier band (§4.3) | close 100% at `bid × 0.998` |
| Time stop | 30 trading days held | close 100% at `bid × 0.998` |
| Take profit (partial) | +25% from entry | close 50% |
| Take profit (final) | +50% from entry | close remaining |
| Kill switch | `KILL_SWITCH` appears | freeze new entries; existing exits continue |

### 4.3 Profit-protection trailing stop (tightens as the gain grows)

Track per open position: `peak_mark` (highest mark since entry, updated each loop) and
`gain_pct = (peak_mark − entry_price) / entry_price`.

| Position gain | Trailing band (drawdown from `peak_mark`) | Hard-stop ratchet (replaces §0.3 floor) |
| --- | --- | --- |
| < +15% | 12% | −8% from entry (unchanged) |
| +15% to +24% | **7%** | move hard stop to **break-even** |
| +25% to +49% | **5%** (partial TP closes 50%) | move hard stop to **+10% from entry** |
| ≥ +50% | **3%** (final TP closes remainder) | move hard stop to **+25% from entry** |

**Rules.** (1) The band and ratchet only ever **tighten**, never widen; `peak_mark` only rises.
(2) Each loop: re-read mark → update `peak_mark` → recompute `gain_pct` → look up band + ratchet
→ if `current_mark ≤ peak_mark × (1 − band)` or `current_mark ≤ ratcheted_hard_stop`, close
immediately. (3) Persist `peak_mark` + active tier in `positions.jsonl` (one record per
`ticker × entry_intent_id`) so state survives across runs. (4) Take-profit rows fire *in
addition*; on a gap through both, prefer the more conservative. (5) A band trigger between
sessions queues the close for the next open (§0.5).

### 4.4 Cooldown

After fully exiting a ticker, **10 trading days** before re-entry.

---

## 5. Confluence bonus

> When **two or more** strategies (§A) fire on the same ticker on the same day, upgrade
> conviction by **one tier** (capped at `high`).

Record the contributing strategies in `signal_source`, e.g. `"trend+breakout"`. A single firing
strategy records just its own name (`"trend"`, `"breakout"`, `"rsi_revert"`).

Example: trend-following medium (score 70) + RSI mean-reversion low (score 48), same ticker →
take `max(tiers) = medium`, upgrade once → **high**.

---

## 6. Order placement procedure

For each candidate that survives all gates:

1. Compose the pre-trade review block:
   `ticker=ACME strategy=trend+breakout score=78 tier=high qty=120 limit=42.25 max_loss=$507 account=Agentic-…XYZ`
2. **If `require_risk_review = true`:** write `proposals/{intent_id}.json`, spawn the
   `risk-reviewer` subagent, wait for its JSON decision, write `reviews/{intent_id}.json`. On
   `reject`, skip steps 3–5: append one `trade-log.jsonl` line with
   `result: "rejected_by_risk_review"` and `rejection_reasons: [...]`, go to step 6. See
   `references/risk-review.md`.
3. **Append a pending entry to `trade-log.jsonl`** (§7) with `result: "pending"`.
4. If `mode = "paper"`: re-append a line with the same `intent_id` and `result: "paper"`.
5. If `mode = "live"`: if `require_manual_confirm`, prompt `Place order? [yes/no]` and wait for
   `yes`; invoke the Robinhood MCP order tool (limit, day, equity, buy); append a closing entry
   with `result: "submitted"`/`"rejected"`/`"error"` and the `mcp_response`.
6. Update `journal/{YYYY-MM-DD}.md` either way.

**The trade-log line must be written before the MCP order tool is invoked.** This is the SOP's
core auditability guarantee.

---

## 7. Logs — two artifacts, both mandatory

### 7.1 `trade-log.jsonl` (repo root, append-only, machine-readable, single analytics source)

One JSON object per line. Written **before** the MCP order tool fires.

```json
{
  "intent_id": "2026-06-12T14:03:21Z-ACME-trend",
  "timestamp_utc": "2026-06-12T14:03:21Z",
  "mode": "live",
  "signal_source": "trend+breakout",
  "ticker": "ACME",
  "side": "buy",
  "qty": 120,
  "limit_price": 42.25,
  "conviction_tier": "high",
  "conviction_score": 78,
  "account_id_masked": "…XYZ",
  "mcp_tool_called": "robinhood.place_limit_order",
  "mcp_response": { "order_id": "abc-123", "status": "queued", "raw": "<full payload>" },
  "result": "submitted",
  "error_msg": null,
  "rules_version": "2026-06-15"
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `intent_id` | yes | Unique. Format `{ISO_TS}-{TICKER}-{strategy}`. Re-used across the pending/closed pair. |
| `timestamp_utc` | yes | ISO 8601, UTC. |
| `mode` | yes | `"paper"` / `"live"`. |
| `signal_source` | yes | Firing strategy or `+`-joined combo, e.g. `"trend"`, `"breakout"`, `"trend+rsi_revert"`. |
| `ticker` | yes | Uppercase US-listed symbol. |
| `side` | yes | `"buy"` for entries; `"sell"` for exits. |
| `qty` | yes | Whole shares. |
| `limit_price` | yes | The limit sent to the MCP. |
| `conviction_tier` | yes | `low` / `medium` / `high`. |
| `conviction_score` | yes | 0–100 from §A. |
| `account_id_masked` | yes | Last 4 chars of the Agentic account id. Never log the full id. |
| `mcp_tool_called` | live only | Robinhood tool invoked. |
| `mcp_response` | live only | Full structured response incl. broker order id. |
| `result` | yes | `"pending"`, `"paper"`, `"submitted"`, `"filled"`, `"rejected"`, `"rejected_by_risk_review"`, `"error"`. |
| `rejection_reasons` | when rejected by review | Array of strings copied verbatim from the Reviewer. |
| `error_msg` | optional | Set on `rejected`/`error`. |
| `rules_version` | yes | Date of this file that produced the decision. |

**Append-only:** never overwrite; re-append a line with the same `intent_id` per state
transition (`pending → submitted → filled`). Reconstruct state by taking the latest line per
`intent_id`.

**Sell-only analytics fields** (added when a sell fills): `entry_intent_id`, `realized_pnl_usd`,
`realized_return_pct`, `holding_period_days`, `exit_reason` (one of `hard_stop`,
`trailing_stop`, `time_stop`, `take_profit_partial`, `take_profit_final`, `manual`).

Quick recipes:

```bash
# latest state per intent
jq -s 'group_by(.intent_id) | map(max_by(.timestamp_utc))' trade-log.jsonl
# realized P&L by strategy
jq -s '[.[] | select(.side=="sell" and .result=="filled")] | group_by(.signal_source)
       | map({src: .[0].signal_source, pnl: ([.[].realized_pnl_usd] | add)})' trade-log.jsonl
```

### 7.2 `journal/{YYYY-MM-DD}.md` (human-facing, one file per day, mandatory — §0.4)

```markdown
# Trade Journal — {YYYY-MM-DD}

## Portfolio Status
- Cash: ${cash_balance}
- Positions: {ticker} ({qty} shares @ ${avg_entry}), ...
- Total Value: ${total_equity}
- Mode: {paper|live}    Market: {open|closed}

## Market Research
### {TICKER}
- 20-day SMA: ${ma20} | 50-day SMA: ${ma50} | RSI14: {rsi} — {trend read} {commentary}
- Strategies: trend={tier or "—"}, breakout={tier or "—"}, rsi_revert={tier or "—"}, combined={tier or "—"}
- News: {one-line headline summary + source}
- Decision: {Entered / Held / Skipped — one-line reason}

(repeat per candidate considered)

## Trades Executed
| Time  | Symbol | Action | Qty | Price   | Reasoning |
|-------|--------|--------|-----|---------|-----------|
| 10:03 | NVDA   | BUY    | 5   | $847.50 | trend medium + breakout + cash OK |

(If no trades: `None today.`)

## Positions Closed
| Time  | Symbol | Reason             | Qty | Entry   | Exit    | P&L    |
|-------|--------|--------------------|-----|---------|---------|--------|
| 14:22 | TSLA   | −8% hard stop §0.3 | 10  | $215.00 | $197.80 | −$172  |

(If none: `None today.`)

## End-of-Day Reflection
{2–4 sentences. What worked, what didn't, what to watch tomorrow. On no-trade days: why
nothing fired and what would change that.}
```

Required sections, in order: Portfolio Status, Market Research (one subsection per candidate
considered, not just traded), Trades Executed, Positions Closed, End-of-Day Reflection. Created
at the first SOP run of the day; reflection written at the last run or by 16:30 ET.

---

## 8. Kill switch

A file named `KILL_SWITCH` at repo root (any contents) means: no new entries; no new
signal-driven sells; existing protective exits (trailing stop, time stop, take profit) **still
run**; signal scans still write the journal. Delete the file to re-enable; log the event.

---

## 9. Stop conditions (SOP-level halts)

Halt the loop and report to the user when: `mode.toml` or `watchlist.json` is missing or
unparseable; Robinhood MCP `tools/list` fails twice in a row; the connected account is not the
Agentic account; `trade-log.jsonl` is unwritable; the daily loss cap was breached < 24h ago; US
regular session is closed (signal scans still run; ordering halts per §0.5).

---

## 10. Versioning

- Every trade-log entry stamps `rules_version` (this file's effective date).
- After editing this file, bump `rules_version` to today's date in the next run.
- Never edit `trade-log.jsonl` retroactively — append corrections as new lines. Never edit a
  prior day's journal — append an `Addendum` section.
