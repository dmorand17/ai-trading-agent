---
name: stock-trader
description: -
  Trade execution for the AI Trading Agent SOP. Place a single user-directed trade ("buy 10 NVDA", "sell half my PLTR at limit 45") or execute a planned set of trades through the risk-reviewer and trade-log gates. Human-in-the-loop: takes user-specified ticker/side/order type, runs the risk-reviewer, and — if it rejects — asks whether to proceed anyway. Supports buy/sell, market/limit, regular and extended hours. Adds bought tickers to the watchlist. Use for "/stock-trader", "buy/sell …", or "execute today's planned trades".
  argument-hint: [ticker] [buy|sell] [qty|$amount] [market|limit] [limit_price]
---

# Stock-trader — user-directed & planned trade execution

This is the **trade-execution entry point** for the SOP. The user names a specific trade (or a
planned set), and you execute each through the audit-trail gates. Read the project `CLAUDE.md`
and `references/strategy.md` — `strategy.md` §0 is non-negotiable and overrides everything here.

Two modes, same gates:
- **Single trade** (the common case) — the user names one trade now ("buy 10 NVDA").
- **Planned set** — execute trades already drafted in today's `journal/{YYYY-MM-DD}.md` Market
  Research, or a list the user hands you. Run each through the loop below in turn.

## What binds every order

- **Prefer limit orders** (§0.1) — recommend ~2% from the current price (buys `ask × 1.02`,
  sells `bid × 0.98`). Market only when a limit can't fill the intent or the user asks for one.
- **Extended hours allowed** (§0.2) — confirm the session and pass the matching `market_hours`.
  Halt only if the market is fully closed.
- **Proposal → risk-review → pending `data/trade-log.jsonl` line, written BEFORE any MCP order
  tool** (§4, §5). No order tool fires without these.
- **Journal entry** for the day (§0.3), including the End-of-Day Reflection.

## Do this (per trade)

### 1. Parse the user's intent

Extract from the request — ask only for what's genuinely missing:
- **ticker** (required)
- **side** — `buy` or `sell` (required)
- **order type** — `market` or `limit` (default `limit` if unspecified)
- **limit_price** — required for `limit`; propose the §0.1 default (`ask × 1.02` for buys,
  `bid × 0.98` for sells) as a suggested price the user can accept or override.
- **size** — qty (whole shares) **or** `dollar_amount` (required). For sells the user may say
  "all" / "half" — resolve against the live position from `get_equity_positions`.

For a **planned set**, read each trade's ticker/side/size from today's journal Market Research;
if nothing is planned and the user named nothing, say so and stop.

**Before asking for a missing `limit_price` or `size`, show the market context first.** The
moment you have a ticker and side but are missing price or size, pull the quote now and display,
in one block: last/mid price, bid, ask, and the §0.1 suggested limit price. Then ask for
everything still missing in a single prompt. Don't invent side, price, or size, and don't place
until the user confirms.

### 2. Hard preconditions (`CLAUDE.md`) — halt on failure

MCP connected (`tools/list` shows Robinhood order tools) · account is the **Agentic** account ·
market session available (§0.2 — if fully closed, stop and tell the user) · `config/config.toml`
parses · no `KILL_SWITCH` · `data/trade-log.jsonl` writable. On any failure, stop with a written
reason. (The watchlist is a tracked list, not a precondition — `strategy.md` §2.)

### 3. Pull live account + market data

- `get_portfolio` + `get_equity_positions` → cash, total equity, open positions, existing
  exposure in this ticker.
- `get_equity_quotes` → quote (bid/ask/mid) for the §0.1 limit-price math. (If step 1 already
  pulled this, reuse it — don't re-fetch.)
- `get_equity_tradability` → confirm the ticker is tradable / fractional-eligible.

### 4. Track the ticker on the watchlist if it's not there

This is list-curation, not a trade gate (`strategy.md` §2) — the trade proceeds regardless. Read
the cache `data/watchlist.json` to check membership (no MCP fetch for the check). If **buying** a
ticker not in the cache:
- `add_to_watchlist(list_id, symbols=[TICKER])` (resolve `list_id` via `get_watchlists` if not
  cached).
- **Update `data/watchlist.json` locally** — append the symbol and bump `fetched_at_utc` (§5.4).
- Tell the user the ticker was added.

(Selling a ticker you hold but isn't on the list does **not** require an add.)

### 5. Risk review (always run) → on reject, ask the user

Write `proposals/{intent_id}.json` (schema in `references/risk-review.md` §3 / the risk-reviewer
agent), including the `account_snapshot` and `market_status`. Spawn the **`risk-reviewer`**
subagent (`references/risk-review.md` §7 spawn prompt). Write `reviews/{intent_id}.json` with its
decision.

- **`approve`** → proceed to step 6.
- **`reject`** → **do not silently skip.** Present the rejection to the user verbatim (the cited
  `reasons`) and ask whether to proceed anyway:

  > The risk-reviewer rejected this trade:
  > - `§0.1 order type: limit_price is >5% through the market`
  >
  > Proceed anyway, adjust the order, or cancel?

  Use the `AskUserQuestion` tool (options: **Proceed anyway** · **Adjust order** · **Cancel**).
  - **Proceed anyway** → record the override (see below) and continue to step 6.
  - **Adjust** → take the new parameters and re-run from step 3 (new `intent_id`).
  - **Cancel** → log `result: "rejected_by_risk_review"` with the reasons, write the journal, stop.

  Record an override in both logs: trade-log `result: "submitted"` with
  `"override_risk_review": true` and `"override_reasons": [<the reviewer's reasons>]`; journal
  Trades-Executed reasoning notes "user override of risk-review reject: <reasons>".

### 6. Write the pending trade-log line, then place the order

1. **Append the `pending` `data/trade-log.jsonl` line BEFORE any MCP order tool** (§4, §5.1). Set
   `order_type`; `dollar_amount` vs `limit_price` per order type; `side` = buy/sell.
2. Execute by `config/config.toml::mode`:
   - **paper** → re-append a line with `result: "paper"`. No MCP call.
   - **live** → `review_equity_order` first (unless the user explicitly said "skip review"), then
     `place_equity_order`. Re-append a closing line with `result:
     "submitted"`/`"filled"`/`"rejected"`/`"error"` and the full `mcp_response`.
   - **Order params by type:** limit → `type=limit`, `limit_price`, `time_in_force=gfd`, the
     session-appropriate `market_hours`. market → `type=market` with `quantity` (whole shares) or
     `dollar_amount` (fractional), session-appropriate `market_hours`.
3. **Update `data/positions.jsonl`** (§5.3): on a buy fill, recompute `total_qty` +
   `avg_entry_price` and append a new line. On a sell, reduce `total_qty` (or `0` if fully
   closed) and add the §5.1 sell-only analytics fields to the trade-log line (`entry_intent_id`,
   `realized_pnl_usd`, `realized_return_pct`, `holding_period_days`).

### 7. Update the journal

Append to `journal/{YYYY-MM-DD}.md` (`strategy.md` §5.2) — create it with the standard sections
if this is the day's first run. Fill Trades Executed (and Positions Closed for sells), and note
in the reasoning that this was a user-directed trade (and any risk-review override).

After the day's trades are done, write the **End-of-Day Reflection** (`strategy.md` §5.2) — 2–4
sentences through the Peter Lynch lens: are the winners still worth holding, is any thesis
deteriorating, was anything sold too early. (Ongoing P&L refresh and the vs-SPY benchmark live in
the `portfolio-review` skill, not here.)

## Notification

Send one notification when an order is placed (paper or live) via `scripts/notify.sh` (read
`.env` for `NTFY_TOKEN`; if missing, emit the summary as the final session line).

```bash
./scripts/notify.sh -t "stock-trader" -p 3 -T "moneybag" "Bought 10 NVDA @ $847.50 [live, user-directed]"
```

## Report back (≤5 lines)

Orders placed (ticker · side · qty · type · price · mode) · risk-review decision (approve /
reject → overridden|cancelled) · watchlist updated? · P&L realized (sells) or position recorded
(buys) · paths to `data/trade-log.jsonl` and today's journal.
