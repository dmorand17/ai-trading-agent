# Trading Strategy & Rules

The single authoritative reference for **what to buy, how to size it, when to exit, and the
mandatory log schemas.** This file replaces the old signal-by-signal split — the trade ideas
now come from a small set of classic, price-based strategies (§A), not from external cluster
feeds.

Everything here is tunable **except §0**. `config.toml` is the runtime source of truth for
execution mode, cash reserve, and the universe-list pointer; the trading universe itself lives
on Robinhood (pulled via the MCP). This file is the source of truth for strategy and sizing.

---

## 0. Non-negotiable rules (these always win)

If anything below conflicts with §0, **§0 wins**. Bright-line invariants.

### 0.1 Position cap: 15% per single position

- **Universal cap: 15% of total portfolio value per single ticker.** Exposure =
  `(open_qty × current_mark) / total_equity`. Includes pre-existing holdings. No per-symbol
  overrides.
- **Cash reserve interacts:** total deployed capital still respects `cash_reserve_pct` (§2.3) —
  you cannot push cash below the reserve floor, even if the per-position cap would otherwise
  allow it.
- The invariant: a per-position cap of 15% and a cash-reserve floor are *always* enforced. The
  SOP may never trade past them.

### 0.2 Order type: limit only, within 0.2% of ask

- Never `market`. Never `stop_market`. Never `market-on-close`.
- Entry limit = `current_ask × 1.002`. Exit limit = `current_bid × 0.998`.
- If the spread is so wide that `current_ask × 1.002` is still inside the spread, skip the
  trade — the book is too thin.

### 0.3 Trailing stop: tiered band, close without waiting

Single mark-based stop, in flight on every open position from day 1.

- Track per open position: `peak_mark = max(entry_price, max mark observed since entry)` and
  `gain_pct = (peak_mark − entry_price) / entry_price`.
- The trailing band tightens as `gain_pct` rises:

  | Position gain | Trailing band (drawdown from `peak_mark`) |
  | --- | --- |
  | < +15%       | 12% |
  | +15% to +24% | 8% |
  | +25% to +49% | 6% |
  | ≥ +50%       | 4% |

- On every loop: re-read `current_mark` → update `peak_mark` → recompute `gain_pct` → look up
  band → if `current_mark ≤ peak_mark × (1 − band)`, submit a closing limit at
  `current_bid × 0.998` **immediately**.
- The band only ever tightens; `peak_mark` only rises. No averaging down, no "wait for the
  bounce," no overriding by strategy score.
- On day 1, `peak_mark = entry_price`, so the worst-case stop is **12% below entry**. As the
  position rises, the floor ratchets up with `peak_mark`.
- Mechanics (persistence, gap-through-stop, between-session triggers) in §4.3.

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
  trailing-stop exit (§0.3) that fires after close is queued for the next open and logged.

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
- **Caution:** mean-reversion entries get a tighter watch — the §0.3 trailing stop (12% from
  entry on day 1) is the backstop if the "dip" keeps falling.

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

The SOP reads `config.toml` at repo root **on every invocation, before any order tool is
touched.** If the file is missing, create it with paper defaults and report to the user.

### 1.1 `config.toml` schema

```toml
mode = "paper"                              # "paper" | "live"
live_allowlist = []                         # [] = all eligible in live; ["AAPL"] = only AAPL goes live
require_manual_confirm = true               # pause for explicit "yes" before each live order
block_tickers = []                          # global blocklist, overrides everything
daily_loss_cap_pct = 0.02                   # halt new entries when day P&L ≤ −this × equity
cash_reserve_pct = 0.10                     # minimum cash floor as a fraction of equity
sop_universe_list_name = "Agent WatchList"  # Robinhood watchlist used as the universe (display_name)
discovery_mode = false                      # true = ignore the universe filter (paper-mode discovery)
require_risk_review = true                  # spawn the risk-reviewer subagent before each order
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
`config.toml`, save, next invocation honors it.

---

## 2. Universe & cash reserve

The trading universe lives on Robinhood; the cash reserve lives in `config.toml`.

### 2.1 Universe source

- The SOP universe is the Robinhood watchlist whose `display_name` equals
  `config.toml::sop_universe_list_name`. The SOP pulls it fresh each invocation via
  `get_watchlists` (match by name → resolve to `list_id`) and `get_watchlist_items`.
- **Filter to equity only.** Drop items whose `object_type ≠ "instrument"` (crypto pairs,
  indexes, futures). The SOP only trades US-listed common equity.
- The SOP **never writes** to the Robinhood watchlist. Add/remove names via the Robinhood app
  (or `add_to_watchlist` / `remove_from_watchlist` only with explicit user confirmation in chat).
- If the named list cannot be found, halt (precondition #5 in `CLAUDE.md`) and tell the user.

### 2.2 Universe filter

- **Default (`discovery_mode = false`):** no order for a ticker outside the universe.
  Off-universe names that score are still logged in Market Research with
  `Decision: Skipped — not on universe list`.
- **`discovery_mode = true`:** no universe filter. Score whatever the SOP encounters. Paper
  mode only — do not flip this on in live.

### 2.3 Cash reserve

- Source: `config.toml::cash_reserve_pct` (fraction of equity, e.g. `0.10`).
- Compute `deployed_pct = (total_equity − cash_balance) / total_equity` each loop.
- A new buy may not push `deployed_pct` above `1 − cash_reserve_pct`.
- Example: `equity = $20,000`, `cash_reserve_pct = 0.10` → deploy ≤ $18,000, keep ≥ $2,000
  cash. If a candidate buy would breach the floor, reduce `qty` to fit; never below the §3.1
  minimum.

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
§0.1 15% per-position cap and the §2.3 cash-reserve floor. If clamping drops `qty` below 1
share, skip and log `Decision: Skipped — sizing collapsed to zero (reserve or position cap)`.

### 3.2 Hard caps

- **Per-ticker:** total exposure ≤ 15% of equity (§0.1). A new buy may not push past.
- **Cash-reserve floor:** total deployed ≤ `(1 − cash_reserve_pct) × equity` (§2.3).
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

The §0.3 trailing stop and the time stop are always in flight. Whichever fires first wins.

| Exit reason | Trigger | Action |
| --- | --- | --- |
| Trailing stop | drawdown from `peak_mark` ≥ tier band (§0.3) | close 100% at `bid × 0.998`, no waiting |
| Time stop | 30 trading days held | close 100% at `bid × 0.998` |
| Kill switch | `KILL_SWITCH` appears | freeze new entries; existing exits continue |

### 4.3 Trailing-stop mechanics

The trailing rule and band table live in §0.3. This section covers the supporting mechanics.

- **State persistence:** write `peak_mark` per open position to `positions.jsonl` (one record
  per `ticker × entry_intent_id`) so trailing state survives across runs. Schema:
  `{ticker, entry_intent_id, entry_price, qty, peak_mark, last_updated_utc}`. Append-only;
  reconstruct state by taking the latest line per `(ticker, entry_intent_id)`.
- **Loop tick:** on every SOP invocation, for each open position — re-read `current_mark`,
  update `peak_mark = max(peak_mark, current_mark)`, look up the band from the §0.3 table by
  `gain_pct = (peak_mark − entry_price) / entry_price`, check
  `current_mark ≤ peak_mark × (1 − band)`.
- **Gap-through-stop:** if the position opens through the stop, exit immediately at the open
  via a limit at `current_bid × 0.998`; do not wait for a retest.
- **Between sessions:** a stop trigger observed when the market is closed queues the close
  for the next open (§0.5). Log the queued exit immediately; submit at the open.

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
`realized_return_pct`, `holding_period_days`, `exit_reason` (one of `trailing_stop`,
`time_stop`, `manual`).

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
| 14:22 | TSLA   | trailing stop §0.3 | 10  | $215.00 | $189.20 | −$258  |

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
signal-driven sells; existing protective exits (trailing stop, time stop) **still run**; signal
scans still write the journal. Delete the file to re-enable; log the event.

---

## 9. Stop conditions (SOP-level halts)

Halt the loop and report to the user when: `config.toml` is missing or unparseable; the SOP
universe list cannot be fetched from Robinhood (named list not found, or the watchlist call
fails twice in a row); Robinhood MCP `tools/list` fails twice in a row; the connected account
is not the Agentic account; `trade-log.jsonl` is unwritable; the daily loss cap was breached
< 24h ago; US regular session is closed (signal scans still run; ordering halts per §0.5).

---

## 10. Versioning

- Every trade-log entry stamps `rules_version` (this file's effective date).
- After editing this file, bump `rules_version` to today's date in the next run.
- Never edit `trade-log.jsonl` retroactively — append corrections as new lines. Never edit a
  prior day's journal — append an `Addendum` section.
