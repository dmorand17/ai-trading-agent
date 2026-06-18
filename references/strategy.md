# Trading Strategy & Rules

The single authoritative reference for **how trades are placed, how positions are tracked, and
the mandatory log schemas.** This is a for-fun project running manually for now — the rules are
deliberately light. `config.toml` is the runtime source of truth for execution mode and
the universe-list pointer; the trading universe itself lives on Robinhood (pulled via the MCP).

This phase is **manual / human-in-the-loop**. The autonomous daily loop and a programmatic
stock screener are roadmap items (see the README) — for now the user picks the trades and the
agent executes them through the audit-trail gates below.

Everything here is tunable **except §0**.

---

## 0. Non-negotiable rules (these always win)

If anything below conflicts with §0, **§0 wins**. Bright-line invariants.

### 0.1 Prefer limit orders

- **Default to a limit order.** Recommend a limit price **~2% from the current price**:
  - Buys: `limit_price = current_ask × 1.02` (rounded to a sensible tick).
  - Sells: `limit_price = current_bid × 0.98`.
- Use a **market order** only when a limit can't fill the intent — e.g. a fractional-share buy
  sized by dollar amount (`dollar_amount` market order), or when the user explicitly asks for a
  market order.
- The ~2% figure is a starting recommendation, not a hard rule. The user may accept, tighten,
  or widen it per trade.
- **Default `time_in_force`:** `gtc` (good till cancelled) for limit orders; `gfd` (good for
  day) for market orders. The user may override per trade.

### 0.2 Extended-hours trading is allowed

- Orders may be placed during regular **or** extended hours. There is no regular-session-only
  restriction.
- Still confirm the market session state before placing (regular / pre-market / after-hours /
  closed) and pass the matching `market_hours` value to the order tool. If the market is fully
  closed (no session at all), do not place — tell the user.

### 0.3 Journal mandatory every day there is activity

- A human-readable `journal/{YYYY-MM-DD}.md` must be created/updated on every day the SOP runs
  and does anything. Template in §5.2.
- On a no-trade day where the user still ran a scan, write `None today.` under Trades Executed
  and record what was looked at and why nothing was taken.

---

## 1. Mode handling (paper / live)

The SOP reads `config.toml` **on every invocation, before any order tool is touched.**
If the file is missing, create it with paper defaults and report to the user.

### 1.1 `config.toml` schema

```toml
mode = "paper"                              # "paper" | "live"
sop_universe_list_name = "Agent WatchList"  # Robinhood watchlist (display_name); cached to data/watchlist.json (§2)
require_risk_review = true                  # risk-reviewer subagent gates every order; MANDATORY in live
```

### 1.2 Paper mode (default)

- All pre-trade review blocks run normally.
- **No MCP order tool is invoked.**
- `data/trade-log.jsonl` entries are appended with `mode: "paper"` and `result: "paper"`.

### 1.3 Live mode

Live mode places real orders. `require_risk_review = true` is **mandatory in live mode**: the
risk-reviewer subagent is the pre-trade gate. If `mode = "live"` and `require_risk_review =
false`, the SOP halts and refuses to place orders.

Pre-flight on every order: `tools/list` returns Robinhood order tools; the MCP account is the
user-confirmed **Agentic** account (never the primary individual account); no `KILL_SWITCH`;
`data/trade-log.jsonl` writable; the risk-reviewer returned `approve`.

---

## 2. Universe (a tracked/research list, cached locally — not a trade gate)

The universe is the Robinhood watchlist whose `display_name` equals
`config.toml::sop_universe_list_name`. It is a **tracked list and research seed**, cached
locally to `data/watchlist.json` (§5.4). **It does not gate trades** — the `stock-trader` skill
may trade any ticker, on the list or not.

**Refresh policy (cache-first — this is the canonical definition; other files reference it):**

- **Read the cache by default.** Resolve the universe from `data/watchlist.json`; make **no** MCP
  watchlist call on a normal run.
- **Refresh from the MCP only when** (a) the user explicitly asks to refresh, (b) the cache is
  missing, or (c) the weekly `portfolio-review` runs (the standing refresh point). To refresh:
  `get_watchlists` (match by name → `list_id`) → `get_watchlist_items`, **filter to equity** (drop
  items whose `object_type ≠ "instrument"` — crypto pairs, indexes, futures), then rewrite
  `data/watchlist.json` with a fresh `fetched_at_utc`.
- **On a failed refresh:** fall back to the existing cache, note staleness, and continue — do not
  halt. (Compare `fetched_at_utc` to the current date the session already knows; no clock call.)

---

## 3. Trading rules (how candidates are chosen)

> **User-defined for now.** The user picks what to buy and sell. A programmatic stock screener
> that surfaces candidates automatically is a roadmap item (see the README). Until then, this
> section is the user's discretion plus the philosophy below.

### 3.1 Trading philosophy — Peter Lynch, "let your winners run"

The guiding style is Peter Lynch's:

- **Let your winners run.** Do not trim a position just because it's up. The biggest gains come
  from holding the rare multi-bagger through the noise.
- **Don't pull the flowers and water the weeds.** Lynch's warning: don't sell your winning
  stocks to add to your losers. It only takes a handful of massive winners to make a lifetime of
  investing successful — protect them.
- Bias toward holding conviction positions; be slow to sell strength and quick to question a
  thesis that's deteriorating.

Concrete entry/exit rules (e.g. a defined trailing stop, time stop, or rebalancing logic) are
**deferred** — see the README roadmap. For now exits are user-directed.

---

## 4. Order placement procedure

For each trade the user directs:

1. Compose the pre-trade review block:
   `ticker=ACME side=buy type=limit qty=… limit_price=… account=Agentic-…XYZ`
2. **If `require_risk_review = true`:** write `proposals/{intent_id}.json`, spawn the
   `risk-reviewer` subagent, wait for its JSON decision, write `reviews/{intent_id}.json`. On
   `reject` in the autonomous loop, skip and log `result: "rejected_by_risk_review"`. In
   `stock-trader` (human-in-the-loop), surface the rejection and let the user decide. See
   `references/risk-review.md`.
3. If `mode = "paper"`: append a line to `data/trade-log.jsonl` with `result: "paper"`. No MCP call.
4. If `mode = "live"`: invoke the Robinhood MCP order tool; **then** append a single entry to
   `data/trade-log.jsonl` with `result: "submitted"`/`"filled"`/`"rejected"`/`"error"` and the
   `mcp_response`.
5. Update `journal/{YYYY-MM-DD}.md` either way.
6. On a buy fill, record/refresh the position in `data/positions.jsonl` (§5.3).

---

## 5. Logs & state — three artifacts

### 5.1 `data/trade-log.jsonl` (append-only, machine-readable, single analytics source)

One JSON object per line. Written immediately after the MCP order tool returns (or immediately for paper/rejected entries). Gitignored — kept local.

```json
{
  "intent_id": "2026-06-12T14:03:21Z-ACME-buy",
  "timestamp_utc": "2026-06-12T14:03:21Z",
  "mode": "live",
  "ticker": "ACME",
  "side": "buy",
  "order_type": "limit",
  "dollar_amount": null,
  "qty": 5,
  "limit_price": 42.25,
  "account_id_masked": "…XYZ",
  "mcp_tool_called": "place_equity_order",
  "mcp_response": { "order_id": "abc-123", "state": "filled", "raw": "<full payload>" },
  "result": "filled",
  "error_msg": null,
  "rules_version": "2026-06-16"
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `intent_id` | yes | Unique. Format `{ISO_TS}-{TICKER}-{side}`. Re-used across the pending/closed pair. |
| `timestamp_utc` | yes | ISO 8601, UTC. |
| `mode` | yes | `"paper"` / `"live"`. |
| `ticker` | yes | Uppercase US-listed symbol. |
| `side` | yes | `"buy"` or `"sell"`. |
| `order_type` | yes | `"limit"` or `"market"`. |
| `dollar_amount` | market+fractional | Set for dollar-sized market orders; null otherwise. |
| `qty` | yes | Whole or fractional shares (up to 6 decimals). For market entries, populated post-fill from MCP response. |
| `limit_price` | limit orders | The limit sent to the MCP; null for market orders. |
| `account_id_masked` | yes | Last 4 chars of the Agentic account id. Never log the full id. |
| `mcp_tool_called` | live only | Robinhood tool invoked. |
| `mcp_response` | live only | Full structured response incl. broker order id. |
| `result` | yes | `"paper"`, `"submitted"`, `"filled"`, `"rejected"`, `"rejected_by_risk_review"`, `"error"`. |
| `rejection_reasons` | when rejected by review | Array of strings copied verbatim from the Reviewer. |
| `error_msg` | optional | Set on `rejected`/`error`. |
| `rules_version` | yes | Date of this file that produced the decision. |

**Sell-only analytics fields** (added when a sell fills): `entry_intent_id`, `realized_pnl_usd`,
`realized_return_pct`, `holding_period_days`.

**Append-only:** never overwrite; re-append a line with the same `intent_id` per state
transition (e.g. `submitted → filled`). Reconstruct state by taking the latest line per
`intent_id`.

Quick recipes:

```bash
# latest state per intent
jq -s 'group_by(.intent_id) | map(max_by(.timestamp_utc))' data/trade-log.jsonl
# realized P&L on closed sells
jq -s '[.[] | select(.side=="sell" and .result=="filled")] | map(.realized_pnl_usd) | add' data/trade-log.jsonl
```

### 5.2 `journal/{YYYY-MM-DD}.md` (human-facing, one file per day, mandatory — §0.3)

```markdown
# Trade Journal — {YYYY-MM-DD}

## Portfolio Status
- Cash: ${cash_balance}
- Positions: {ticker} ({qty} shares @ ${avg_entry}, {unrealized P&L}), ...
- Total Value: ${total_equity}
- Mode: {paper|live}    Session: {regular|pre-market|after-hours|closed}

## Market Research
{Keep it concise — a brief, not an analyst report.}
- Catalysts: 3–6 bullets (each one line + source), limited to held or watchlist names.
- Today's idea(s): at most 1–2 short notes — ticker · why · indicative size.
{No full-universe scoring table and no multi-paragraph candidate deep-dives in the journal. If a
programmatic score is ever produced, its table belongs in a gitignored `data/` file, not here.
Don't add a separate "Draft Trade Ideas" section — fold ideas into this one. Target ~30–40 lines
for the whole journal.}

## Trades Executed
| Time  | Symbol | Action | Qty | Price   | Reasoning |
|-------|--------|--------|-----|---------|-----------|
| 10:03 | NVDA   | BUY    | 5   | $847.50 | user-directed; trend intact |

(If no trades: `None today.`)

## Positions Closed
| Time  | Symbol | Reason | Qty | Entry   | Exit    | P&L    |
|-------|--------|--------|-----|---------|---------|--------|
| 14:22 | TSLA   | user sell | 10 | $215.00 | $189.20 | −$258  |

(If none: `None today.`)

## End-of-Day Reflection
{2–4 sentences. What worked, what didn't, what to watch tomorrow.}
```

### 5.3 `data/positions.jsonl` (append-only, local position state)

Tracks each open position's **total quantity** (aggregated across multiple buys) and **current
unrealized P&L**. Gitignored — kept local. One record per update; reconstruct state by taking
the latest line per `ticker`.

```json
{
  "ticker": "AMD",
  "total_qty": 0.153058,
  "avg_entry_price": 548.81,
  "current_mark": 561.20,
  "unrealized_pnl_usd": 1.90,
  "unrealized_pnl_pct": 2.26,
  "last_updated_utc": "2026-06-16T19:37:30Z"
}
```

| Field | Notes |
| --- | --- |
| `ticker` | Uppercase symbol. |
| `total_qty` | Sum of all open share lots (whole or fractional, up to 6 decimals). |
| `avg_entry_price` | Cost-basis-weighted average entry across all open lots. |
| `current_mark` | Latest observed mark at update time. |
| `unrealized_pnl_usd` | `(current_mark − avg_entry_price) × total_qty`. |
| `unrealized_pnl_pct` | `(current_mark − avg_entry_price) / avg_entry_price × 100`. |
| `last_updated_utc` | ISO 8601, UTC. |

On a buy fill: recompute `total_qty` and `avg_entry_price` and append a new line. On a full
sell: append a line with `total_qty: 0` (closed). On a partial sell: reduce `total_qty`,
keep `avg_entry_price`.

### 5.4 `data/watchlist.json` (local cache of the Robinhood universe)

The locally-cached copy of the SOP universe (§2). Gitignored — kept local. Single JSON object,
overwritten on each refresh. The cache is the default source; refresh policy is in §2.

```json
{
  "list_name": "Agent WatchList",
  "fetched_at_utc": "2026-06-16T13:00:00Z",
  "symbols": ["AMD", "NVDA", "CRWD", "..."]
}
```

| Field | Notes |
| --- | --- |
| `list_name` | The `display_name` matched against `config.toml::sop_universe_list_name`. |
| `fetched_at_utc` | ISO 8601, UTC. Timestamp of the last refresh (§2). |
| `symbols` | Uppercase equity tickers (post equity-filter). |

Written by `market-research` on a refresh, and by `stock-trader` (local append + `fetched_at_utc`
bump) when it adds a bought ticker via `add_to_watchlist`.

---

## 6. Kill switch

A file named `KILL_SWITCH` at repo root (any contents) means: no new orders. Signal scans and
journal entries still run. Delete the file to re-enable; log the event.

---

## 7. Stop conditions (SOP-level halts)

Halt and report to the user when: `config.toml` is missing or unparseable; Robinhood MCP
`tools/list` fails twice in a row;
the connected account is not the Agentic account; `data/trade-log.jsonl` is unwritable; the
market is fully closed (no session available) and an order was requested.

---

## 8. Versioning

- Every trade-log entry stamps `rules_version` (this file's effective date).
- After editing this file, bump `rules_version` to today's date in the next run.
- Never edit `data/trade-log.jsonl` retroactively — append corrections as new lines. Never edit
  a prior day's journal — append an `Addendum` section.
