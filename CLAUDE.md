# AI Trading Agent SOP — project instructions

This file is the always-loaded dispatcher for the AI Trading Agent SOP. It defines the goal,
the non-negotiable safety rules, the daily loop, and where to load detail on demand. The Claude
Code session is the executor at runtime — there is no application code.

## Goal

**Beat the S&P 500.** The objective is to outperform the S&P 500 (benchmark: SPY total return)
on a risk-adjusted basis over the long run — not to maximize raw return, and not to trade for
its own sake. Every strategy, sizing, and exit rule serves that goal.

- The benchmark is SPY (or ^GSPC) total return over the same period as the trade log.
- "Beating" means net realized + unrealized return after fees exceeds SPY's return over the
  matching window. Track this in the weekly review.
- A losing month that still beats a down S&P is a win; a winning month that trails a ripping
  S&P is a miss. Judge against the benchmark, not zero.
- Capital preservation comes first: the non-negotiable rules in `references/strategy.md` §0
  always win, even when chasing the benchmark would suggest otherwise.

## When this SOP is in play

Engage the SOP when the user asks to: run the SOP / scan for trade ideas / "what should I trade
today"; place a trade or review the trade log; or on a scheduled daily cadence. The phase skills
in `.claude/skills/` (`pre-market`, `market-open`, `daily-summary`, `weekly-review`) are
phase-specific entry points that all defer to this file and `references/strategy.md`.

## Non-negotiable rules (apply always, override everything)

Bright-line invariants. If any conflicts with a strategy score, the rule wins. Full mechanics in
`references/strategy.md` §0.

1. **Never invest more than 15% of total portfolio value in a single position.** Universal cap
   — no per-symbol overrides.
2. **Prefer limit orders; use market orders only when fractional shares are required.** Entry logic: if `floor(tier_$ / ask) ≥ 1`, place a limit order at `min(ask × 1.002, SMA10 × 1.01)` for whole shares. If `floor(tier_$ / ask) < 1` (stock too expensive for even 1 whole share at tier sizing), place a `dollar_amount` market order during `regular_hours` only. Exits always use limit orders at `bid × 0.998` — never market for exits.
3. **A tiered trailing stop protects every open position from day 1.** Track each position's
   `peak_mark` (max of entry and every mark observed since); close immediately when the
   current mark falls below `peak_mark × (1 − band)`. The band tightens as gain grows:
   **12% / 8% / 6% / 4%** at gain tiers **<+15% / +15–24% / +25–49% / ≥+50%**. Day 1: peak =
   entry, so the floor is 12% below entry; as the position rises, the floor ratchets up. No
   averaging down, no waiting. Mechanics in `references/strategy.md` §0.3.
4. **Always write a journal entry for the day, even with zero trades.** No-trade entries record:
   what was scanned, candidates skipped, why.
5. **Never trade when the US market is closed.** Check via the Robinhood MCP (or calendar
   fallback: Mon–Fri 09:30–16:00 ET excluding NYSE holidays). No extended-hours orders.

## Hard preconditions (verify in order, halt on failure)

1. **MCP connected.** Run `tools/list`; confirm Robinhood trading tools are present. If not,
   tell the user the MCP is unreachable and stop.
2. **Account is the dedicated Agentic account** — not the user's primary individual account.
   Robinhood only permits agentic trading from dedicated Agentic accounts.
3. **Market is open.** If closed, signal scans continue but no order tool may be invoked.
4. **`config.toml` exists and parses.** Required: `mode`, `require_risk_review`. If missing,
   create with paper defaults and tell the user. **In live mode, `require_risk_review` must be
   `true`** — the SOP is fully autonomous (no human-in-the-loop confirmation), so the
   risk-reviewer is the mandatory pre-trade gate. If `mode = "live"` and
   `require_risk_review = false`, halt and tell the user.
5. **SOP universe is reachable.** Pull the Robinhood watchlist named in
   `config.toml::sop_universe_list_name` via the MCP (`get_watchlists` → match by `display_name`
   → `get_watchlist_items`). If the named list does not exist, halt and tell the user. If
   `discovery_mode = true`, skip this check (no universe filter).
6. **No kill switch.** If `KILL_SWITCH` exists at repo root, refuse to place orders (scans still
   allowed).
7. **`trade-log.jsonl` is writable.** No order tool may be invoked unless it is.

## Daily SOP loop

```
1. Pull the SOP universe (Robinhood list named in `config.toml::sop_universe_list_name`) via the
   MCP; filter to equity instruments. Refresh quotes/OHLCV for each (Robinhood MCP; web/quote
   fallback).
2. Score each ticker against the three strategies (references/strategy.md §A:
   trend-following, momentum/breakout, RSI mean-reversion). A ticker that fires ≥1 becomes a
   candidate; tier = best firing score, with the §5 confluence upgrade if ≥2 fire.
3. Run the 5-question Decision Framework per candidate (below). Any unsatisfactory answer →
   skip the trade and log the reason.
4. Emit a pre-trade review block per surviving candidate
   (ticker | strategy | score | tier | qty | limit | max_loss).
5. If require_risk_review = true: write proposals/{intent_id}.json + spawn the risk-reviewer
   subagent (references/risk-review.md). Proceed only on "approve"; on "reject" log it and skip.
6. Write the pending trade-log.jsonl line BEFORE any MCP order tool (strategy.md §6, §7).
7. Execute by mode: paper → result "paper", no MCP call. live → place limit order (honoring
   block_tickers), then log the result. No confirmation prompt — execution is autonomous.
8. Scan all open positions for the §0.3 tiered trailing stop. Close on breach.
9. Update journal/{YYYY-MM-DD}.md — mandatory even on zero-trade days (§0.4).
```

## Decision Framework (answer all 5 in writing before every trade)

1. **Current cash balance?** Read from the MCP. The trade must fit available cash and respect
   `cash_reserve_pct` from `config.toml`.
2. **What positions are already open?** Read from the MCP. Block if this ticker is at the 15%
   per-position cap, or not in the SOP universe (unless `discovery_mode = true`).
3. **Recent news?** Quick read (MCP or brief web search). Block on an active going-private,
   bankruptcy, fraud, SEC enforcement, or accounting-restatement headline in the last 14 days.
4. **What do the moving averages / RSI say?** This is also the strategy input — confirm the
   firing strategy's read still holds at execution time.
5. **Risk if the trade goes wrong?** State the day-1 worst-case dollar loss
   (`qty × entry × 0.12`) — the 12% floor from the §0.3 trailing stop at peak = entry — and
   confirm it's within the daily loss cap (`daily_loss_cap_pct`, default 2% of equity) after
   any realized intraday losses.

## Load on demand

| When you need… | Load |
| --- | --- |
| Strategies, sizing, exits, mode, kill switch, log schemas | `references/strategy.md` |
| When/how to spawn the risk-reviewer subagent | `references/risk-review.md` |
| Robinhood MCP tool reference (signatures, defaults, gotchas) | `references/robinhood-mcp.md` |
| Ticker → theme mapping for trade-log tagging and P&L analytics | `themes.toml` |

Do not preload references unless the loop needs them.

## Watchlist maintenance

Whenever the Agent WatchList is modified (tickers added or removed via `add_to_watchlist` /
`remove_from_watchlist`), **update `themes.toml` in the same operation** — before the
conversation ends. `themes.toml` is the canonical source of ticker → theme metadata and must
stay in sync with the Robinhood list. The `theme` field in every `trade-log.jsonl` entry is
populated from `themes.toml`; stale mappings corrupt theme-level P&L analytics.

## Two logs, both mandatory

- **`trade-log.jsonl`** (repo root, append-only, machine-readable) — one line per order state
  transition, written **before** the MCP order tool fires. The single analytics source across
  all days. Schema in `strategy.md` §7.1.
- **`journal/{YYYY-MM-DD}.md`** (human-readable, one per day) — Portfolio Status → Market
  Research → Trades Executed → Positions Closed → End-of-Day Reflection. Mandatory every trading
  day, including no-trade days. Template in `strategy.md` §7.2.

## Safety defaults (overridden only by explicit user instruction)

- Default mode: **paper**.
- Default side: **buy** only. Sells happen only via exit rules in `strategy.md` §4.2.
- Default asset class: **US-listed common equity**. No options, crypto, OTC.
- Default order type: **limit**, never market. No leverage, no shorting, no extended hours.

## Stop conditions

Halt new entries and tell the user when: the market is closed; the daily loss cap is breached;
the MCP goes unreachable mid-loop; `KILL_SWITCH` appears; `config.toml` becomes unparseable; or
the SOP universe list cannot be fetched from Robinhood.

## Reporting back

After each loop, summarize in ≤5 lines: candidates surfaced (by tier) · orders placed (count +
mode) · open positions touched (incl. any trailing-stop exits) · stop conditions hit · paths to
today's `trade-log.jsonl` and `journal/{YYYY-MM-DD}.md`.

## Git practices (inherited)

- Use `git-c` instead of `git` when pushing to a remote. If `git-c` fails with a "failed to
  connect to the docker API" error, ask the user whether to start colima via `colima start`.
