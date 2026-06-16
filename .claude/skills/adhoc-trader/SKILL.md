---
name: adhoc-trader
description: On-demand, user-directed trade execution for the AI Trading Agent SOP. Use when the user explicitly asks to place a specific trade right now — "buy 10 NVDA", "sell half my PLTR at limit 45", "/adhoc-trader". Unlike the autonomous daily loop, this skill is human-in-the-loop: it takes a user-specified ticker/side/order type, scores it against strategy.md, runs the risk-reviewer, and — if the reviewer rejects — asks the user whether to proceed anyway. Supports buy/sell, market/limit. Adds the ticker to the watchlist if it's not already there.
argument-hint: [ticker] [buy|sell] [qty|$amount] [market|limit] [limit_price]
---

# Adhoc-trader — user-directed, on-demand trade execution

This is the **on-demand** counterpart to the autonomous daily SOP loop. The user names a specific
trade and you execute it through the same audit-trail gates. Read the project `CLAUDE.md` and
`references/strategy.md` — `strategy.md` §0 is non-negotiable and overrides everything here.

## How this differs from the autonomous SOP (read first)

This skill is **human-in-the-loop**. Three SOP defaults are deliberately relaxed because a human is
directing each trade in real time:

| SOP default (autonomous loop) | Adhoc-trader behavior |
| --- | --- |
| Buy-only; sells happen only via §4.2 exit rules | **User may buy or sell.** Sells are allowed when the user explicitly directs one. |
| Limit only; market only for fractional entries | **User may choose market or limit, buy or sell.** Default to limit if the user doesn't specify; confirm before placing a market order. |
| Universe-filtered (no trade off the watchlist) | **Off-watchlist tickers are allowed** — and the ticker is **added to the watchlist** (see step 4). |
| Risk-reviewer `reject` → trade is skipped | **`reject` → prompt the user** whether to override and proceed (see step 7). |

What does **NOT** change — the §0 non-negotiables and the audit trail still bind every order:
- **15% per-position cap** (§0.1) and the **cash-reserve floor** (§2.3) are hard limits. The
  risk-reviewer enforces them; an override does not waive them — warn loudly and still record the
  breach (see step 7).
- **Trailing stop** (§0.3) protects every resulting buy from day 1 — record `peak_mark` in
  `positions.jsonl`.
- **Never trade when the market is closed** (§0.5) — halt before any order tool if the session is
  closed. Queue nothing; just tell the user.
- **Proposal → risk-review → pending `trade-log.jsonl` line, written BEFORE any MCP order tool**
  (§6, §7). No order tool fires without these.
- **Journal entry** for the day (§0.4).

## Do this

### 1. Parse the user's intent

Extract from the request — ask only for what's genuinely missing:
- **ticker** (required)
- **side** — `buy` or `sell` (required)
- **order type** — `market` or `limit` (default `limit` if unspecified)
- **limit_price** — required for `limit`; propose the §0.2 default — `min(ask × 1.002,
  SMA10 × 1.01)` for buys / `bid × 0.998` for sells — as a suggested price the user can accept or
  override.
- **size** — qty (whole shares) **or** `dollar_amount` (required). For sells the user may say
  "all" / "half" — resolve against the live position from `get_equity_positions`.

**Before asking the user for any missing `limit_price` or `size`, show the market context first.**
The moment you have a ticker and side but are missing the price or size, do step 3's quote +
historicals pull **now** and display, in one block: last/mid price, bid, ask, SMA10, SMA20, SMA50,
RSI14, and the §0.2 suggested limit price. Then ask for everything still missing (price and/or
size) in a single prompt — never ask for size before the user has seen the quote and SMAs. Don't
invent side, price, or size, and don't place until the user confirms.

### 2. Hard preconditions (`CLAUDE.md`) — halt on failure

MCP connected (`tools/list` shows Robinhood order tools) · account is the **Agentic** account ·
market **open** (§0.5 — if closed, stop and tell the user; this skill never queues) · `config.toml`
parses · no `KILL_SWITCH` · `trade-log.jsonl` writable. On any failure, stop with a written reason.

### 3. Pull live account + market data

- `get_portfolio` + `get_equity_positions` → cash, total equity, open positions, existing exposure
  in this ticker.
- `get_equity_quotes` + `get_equity_historicals` → quote (bid/ask/mid), and OHLCV for SMA10 /
  SMA20 / SMA50 / RSI14 (`strategy.md` §A inputs) and the §0.2 limit-price math. (If step 1
  already pulled these to show the user the limit-price context, reuse that data — don't re-fetch.)
- `get_equity_tradability` → confirm the ticker is tradable / fractional-eligible for this account.

### 4. Add the ticker to the watchlist if it's not there

Pull the SOP universe (`get_watchlists` → match `config.toml::sop_universe_list_name` →
`get_watchlist_items`). If **buying** a ticker not on the list:
- `add_to_watchlist(list_id, symbols=[TICKER])`.
- **Immediately update `themes.toml`** in the same operation (`CLAUDE.md` watchlist-maintenance
  rule) — add the ticker under the best-fit theme; if no theme fits, add it under a new or
  `misc`/`uncategorized` key and tell the user. Stale mappings corrupt theme-level P&L analytics.
- Tell the user the ticker was added and to which theme.

(Selling a ticker you hold but isn't on the list does **not** require an add — you're reducing, not
establishing, exposure. Note it but don't add.)

### 5. Score against the strategy set (informational, not gating)

Score the ticker against `strategy.md` §A (trend / breakout / RSI mean-reversion) and report the
firing strategies + tier (§3.1, §5). For a **user-directed** trade this is **advisory** — the user
chose the trade, so a no-fire score does not auto-skip. But surface it plainly: if nothing fires,
say so ("no strategy fires on TICKER right now — trend is down / RSI neutral"). Use the score as
`signal_source` / `conviction_*` in the proposal; for a sell or a no-fire buy, set
`signal_source: "adhoc"` and `conviction_tier: "user_directed"`.

### 6. Answer the 5-question Decision Framework (`CLAUDE.md`) in writing

Cash · open positions + existing exposure in this ticker (block at the 15% cap unless this is a
sell) · recent news (block on going-private / bankruptcy / fraud / SEC / restatement in last 14d) ·
MA/RSI read · worst-case loss. For a **buy**, state day-1 worst-case = `qty × entry × 0.12`
(§0.3 floor) and check it against the daily loss cap. For a **sell**, state realized P&L vs the
position's entry instead.

### 7. Risk review (always run) → on reject, ask the user

Write `proposals/{intent_id}.json` (schema in `references/risk-review.md` §3 / the risk-reviewer
agent), including the `universe_snapshot` (post-add, so an added buy ticker is present) and the
`account_snapshot`. Spawn the **`risk-reviewer`** subagent (`references/risk-review.md` §7 spawn
prompt). Write `reviews/{intent_id}.json` with its decision.

- **`approve`** → proceed to step 8.
- **`reject`** → **do not silently skip.** Present the rejection to the user verbatim (the cited
  `reasons`) and ask whether to proceed anyway:

  > The risk-reviewer rejected this trade:
  > - `B.1 position cap: post-trade exposure 16.3% exceeds 15% per-position cap`
  >
  > Proceed anyway, adjust the order, or cancel?

  Use the `AskUserQuestion` tool (options: **Proceed anyway** · **Adjust order** · **Cancel**).
  - **Proceed anyway** → record the override (see below) and continue to step 8.
  - **Adjust** → take the new parameters and re-run from step 5 (new `intent_id`).
  - **Cancel** → log `result: "rejected_by_risk_review"` with the reasons, write the journal, stop.

  **Override guardrail:** even on an explicit override, the §0.1 15% position cap and §2.3
  cash-reserve floor are hard limits — Robinhood may reject the order regardless, and you must
  warn the user in capital terms ("this puts NVDA at 18% of equity; the SOP cap is 15%") before
  placing. Record the override in both logs: trade-log `result: "submitted"` with
  `"override_risk_review": true` and `"override_reasons": [<the reviewer's reasons>]`; journal
  Trades-Executed reasoning notes "user override of risk-review reject: <reasons>".

### 8. Write the pending trade-log line, then place the order

1. **Append the `pending` `trade-log.jsonl` line BEFORE any MCP order tool** (§6, §7.1). Set
   `dollar_amount` vs `limit_price` per order type; `side` = buy/sell; `theme` from `themes.toml`.
2. Execute by `config.toml::mode`:
   - **paper** → re-append a line with `result: "paper"`. No MCP call.
   - **live** → `review_equity_order` first (unless the user explicitly said "skip review"), then
     `place_equity_order` (honor `block_tickers` — a blocked ticker is never placed, even on an
     override). Re-append a closing line with `result: "submitted"`/`"filled"`/`"rejected"`/
     `"error"` and the full `mcp_response`.
   - **Order params by type:** limit → `type=limit`, `limit_price`, `time_in_force=gfd`,
     `market_hours=regular_hours`. market → `type=market` with `quantity` (whole shares) or
     `dollar_amount` (fractional), `market_hours=regular_hours`. No extended hours.
3. **Buys only:** record/refresh `peak_mark = entry` in `positions.jsonl` so the §0.3 trailing
   stop is in flight from day 1. **Sells:** if the sell fully exits a position, add the §7.1
   sell-only analytics fields (`entry_intent_id`, `realized_pnl_usd`, `realized_return_pct`,
   `holding_period_days`, `exit_reason: "manual"`).

### 9. Update the journal

Append to `journal/{YYYY-MM-DD}.md` (`strategy.md` §7.2) — create it with the standard sections if
this is the day's first run. Fill Trades Executed (and Positions Closed for sells), and note in the
reasoning that this was a user-directed adhoc trade (and any risk-review override).

## Notification

Send one notification when an order is placed (paper or live) via `scripts/notify.sh` (read `.env`
for `NTFY_TOKEN`; if missing, emit the summary as the final session line).

```bash
./scripts/notify.sh -t "adhoc-trader" -p 3 -T "moneybag" "Bought 10 NVDA @ $847.50 [live, user-directed]"
```

## Report back (≤5 lines)

Order placed (ticker · side · qty · type · price · mode) · risk-review decision (approve / reject
→ overridden|cancelled) · watchlist/themes.toml updated? · trailing stop set (buys) or P&L
realized (sells) · paths to `trade-log.jsonl` and today's journal.
