# Robinhood MCP — tool reference

Reference for the `robinhood-trading` MCP server. Load on demand from `CLAUDE.md`.

All tools are namespaced `mcp__robinhood-trading__*`. The MCP must be connected
(precondition 1 in `CLAUDE.md`); if `tools/list` does not return these, halt the loop.

## Conventions

- **`account_number`** — every account-scoped tool requires this. Resolve it from the user
  or from `get_accounts`; never silently default. Order placement / cancellation also
  require `agentic_allowed=true` on the account. Per the SOP, this is the dedicated
  Agentic account, not the primary individual account.
- **Confirmation discipline** — any tool that writes (orders, watchlist mutations, follow/
  unfollow) must be confirmed against the SOP gates (proposal → risk-reviewer →
  trade-log line) before invocation. `place_equity_order` is the only one that moves money.
- **Idempotency** — `place_equity_order` accepts a `ref_id` (UUID). Generate once per
  logical order; re-send the same `ref_id` on transient retries.
- **Pagination** — list endpoints return a `cursor` field for the next page; pass it back
  as `cursor`. Default to narrow queries (state/symbol/date filters) before paginating.
- **Symbols & IDs** — most equity tools take ticker symbols directly. Watchlist mutations
  for non-equity assets take UUIDs (`currency_pair_ids`, `index_ids`, `option_ids`);
  resolve via `search` (asset_type=`currency_pair` or `market_index`) or
  `get_option_instruments` for options.

## Account & portfolio

### `get_accounts`
List the user's brokerage accounts. Use to look up `account_number` for downstream tools.
Does **not** return reliable buying power — route buying-power questions through
`get_portfolio`.

### `get_portfolio`
- **args:** `account_number`
- Market-value breakdown by asset type plus buying power. Use for "what's my account
  worth?", "how much in options?", "how much can I spend?".

### `get_equity_positions`
- **args:** `account_number`, `cursor?`
- Open equity positions for one account: symbol, quantity, average cost, per-position
  hold breakdowns. Used to refresh `data/positions.jsonl` (total qty + current P&L) and to
  resolve existing exposure before a trade.

## Market data

### `get_equity_quotes`
- **args:** `symbols[]`
- Real-time quotes plus the official last-completed-session close. Above 20 symbols,
  `closes` is omitted with `closes_error` set — keep batches ≤ 20 to retain closes.

### `get_equity_historicals`
- **args:** `symbols[]` (≤ 10), `start_time` (RFC3339 UTC), `end_time?`, `interval?`,
  `bounds?`, `adjustment_type?`
- OHLCV bars across an explicit time range. Useful for context on a ticker the user is
  considering (a stock screener that consumes this is a roadmap item).
- **Interval** is optional — when omitted, the server auto-picks an interval targeting
  ~250 bars and the per-call bar cap does not apply. Provide an explicit interval only
  when you need a specific granularity. The 1-minute bar is named `minute` (not
  `1minute`).
- **bounds** defaults to `regular` (RTH). Use `extended` / `24_5` only when the user
  explicitly asks about extended-hours activity.
- **adjustment_type** defaults to `split` (right for backtesting). `none` for raw,
  `all` for split + dividend (intraday only).

### `get_equity_tradability`
- **args:** `account_number`, `symbols[]` (≤ 10)
- Per-session eligibility + fractional support for the given account. Exact-ticker
  match only. **Call this before `review_equity_order`** to surface restrictions early.

### `search`
- **args:** `query`, `asset_type?` (default `instrument`; also `currency_pair`,
  `market_index`), `limit?`
- Natural-language resolution to instruments / crypto pairs / indexes. Use when the
  user names something by name instead of ticker, or when you need a UUID for a
  watchlist tool.

## Orders — read

### `get_equity_orders`
- **args:** `account_number`, `order_id?`, `state?`, `symbol?`, `placed_agent?`,
  `created_at_gte?`, `cursor?`
- List equity orders newest-first, or single-order mode with `order_id`. **Prefer narrow
  filters** (combine `state` + `symbol` + `created_at_gte`) — the per-page cap is fixed.
- `created_at_gte`: convert user-timezone relative times ("today", "this week") to UTC
  before sending.
- `placed_agent='agentic'` filters to MCP-placed orders — handy for reconciling
  `data/trade-log.jsonl` with what actually fired.

## Orders — write (gated)

These are the only tools that move money or cancel real orders. SOP §4 / §5 require a
proposal + risk-review + pending trade-log line **before** any of these fire.

### `review_equity_order`
- **args:** `account_number`, `symbol`, `side` (`buy`/`sell`), `type` (`market`/`limit`/
  `stop_market`/`stop_limit`), one of `quantity` or `dollar_amount`, `limit_price?`,
  `stop_price?`, `time_in_force?` (`gfd`/`gtc`), `market_hours?` (`regular_hours`/
  `extended_hours`/`all_day_hours`)
- Simulates the order without placing it. Returns the current quote plus pre-trade
  alerts (buying power, PDT, halt, etc.). **Call this by default before
  `place_equity_order`** unless the user has very explicitly said to skip review
  ("just place it, don't review"). A generic "place this order" is not a bypass.
- Parameter rules:
  - Provide exactly one of `quantity` or `dollar_amount`; `dollar_amount` requires
    `type=market`.
  - Fractional shares: only on `type=market` + `market_hours=regular_hours`, eligible
    accounts, ≤ 6 decimals, no short sells.
  - `limit_price` required for `limit`/`stop_limit`; `stop_price` required for
    `stop_market`/`stop_limit`.
  - Fractional and dollar-based orders only place in `regular_hours`.
- Account must be `agentic_allowed=true`.
- **SOP default:** prefer `type=limit` ~2% from the current price (buys `ask × 1.02`, sells
  `bid × 0.98`); use a market order only when a limit can't fill the intent (e.g. a
  fractional-share dollar buy) or when the user explicitly asks (CLAUDE.md non-negotiable #1).

### `place_equity_order`
- **args:** same as `review_equity_order` plus optional `ref_id` (UUID).
- Places the real order. Account must be `agentic_allowed=true`.
- **Idempotency:** generate `ref_id` once per logical order; re-send on transient
  transport failures. New `ref_id` only when the user wants a new order. Omitting
  falls back to a server key (loses client↔gateway idempotency).
- **SOP gates that must pass first:** mode check, risk-reviewer approval, pending
  `data/trade-log.jsonl` line written. See `strategy.md` §4.

### `cancel_equity_order`
- **args:** `account_number`, `order_id`
- Cancels an open order. Always confirm with the user before calling. Resolve
  `order_id` via `get_equity_orders` if the user refers to it by symbol. May be
  rejected if the order already filled / cancelled. Account must be
  `agentic_allowed=true`.

## Watchlists — read

### `get_watchlists`
User-created lists plus curated lists the user follows. Use to look up `list_id`.

### `get_watchlist_items`
- **args:** `list_id`
- Items on the list (stocks/ETFs, crypto pairs, futures, indexes — distinguished by
  `object_type`). No live prices; call `get_equity_quotes` for that.
- **Not for the options watchlist** — use `get_option_watchlist` (the generic shape
  drops option-specific fields and upstream rejects it with 400).

### `get_option_watchlist`
Single-leg option contracts on the user's options watchlist. Works for equity and
index options. Multi-leg strategies set up in the Robinhood app are not surfaced
here.

### `get_popular_watchlists`
Robinhood-curated lists the user can follow (e.g. "100 Most Popular", "Daily Movers").
Returns `list_id` values for `follow_watchlist`.

## Watchlists — write (low-risk, still confirm)

### `create_watchlist`
- **args:** `display_name`, `display_description?`, `icon_emoji?`
- New custom list. Name must be unique among the user's lists. Confirm name before
  calling.

### `update_watchlist`
- **args:** `list_id`, plus at least one of `display_name`, `icon_emoji`,
  `display_description`
- Rename / re-icon a custom list. Curated lists fail with 404.

### `add_to_watchlist`
- **args:** `list_id`, exactly one of `symbols[]` (US stocks/ETFs),
  `currency_pair_ids[]` (crypto UUIDs), or `index_ids[]` (market-index UUIDs)
- Mutually exclusive item-type arrays. For options use `add_option_to_watchlist`
  (separate dedicated watchlist). Futures still require the Robinhood app.
  Already-present items are no-ops.

### `remove_from_watchlist`
- **args:** same shape as `add_to_watchlist`
- Items not on the list are no-ops, not errors.

### `add_option_to_watchlist`
- **args:** `option_ids[]`, `position_type?` (`long` default, or `short`)
- Single-leg adds; for mixed long/short, issue two calls. Source `option_ids` from
  `get_option_instruments`.

### `remove_option_from_watchlist`
- **args:** `option_ids[]`, `position_type?`
- `position_type` must match how the contract was added.

### `follow_watchlist`
- **args:** `list_id`
- Follow a Robinhood-curated list (from `get_popular_watchlists`). Do not use to
  re-add a list the user already owns.

### `unfollow_watchlist`
- **args:** `list_id`
- Unfollow a curated list. The list itself is unchanged.

## Quick lookup — by SOP loop step

| Loop step (`CLAUDE.md` §Manual trading loop) | Tools |
| --- | --- |
| 1. Pull universe / refresh quotes | `get_watchlists`, `get_watchlist_items`, `get_equity_quotes` |
| Account context (cash / open positions) | `get_portfolio`, `get_equity_positions` |
| 3. Pre-trade review block | `get_equity_tradability`, `review_equity_order` |
| 6. Execute (live) | `place_equity_order` |
| 7. Refresh position state | `get_equity_positions`, `get_equity_quotes` |
| Order reconciliation / portfolio review | `get_equity_orders` (filter `placed_agent='agentic'`) |
| Watchlist maintenance | `get_watchlists`, `get_watchlist_items`, `add_to_watchlist`, `remove_from_watchlist` |

## Tools & defaults

- **Prefer limit orders** (§0.1) — `type=limit` ~2% from the current price. Use `type=market`
  only when a limit can't fill the intent (e.g. a fractional-share `dollar_amount` buy) or when
  the user explicitly asks.
- **Extended hours are allowed** (§0.2) — set `market_hours` to match the session
  (`regular_hours` / `extended_hours` / `all_day_hours`). Note: fractional and dollar-based
  orders only place in `regular_hours` (a Robinhood constraint).
- **Options & crypto write tools** — out of scope (US-listed common equity only). Read-side
  tools are fine for context, but no orders.
