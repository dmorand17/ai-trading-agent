---
name: pre-market
description: Pre-market research phase of the AI Trading Agent SOP. Check Robinhood balance + open positions, web-search today's catalysts (earnings, economic data, sector momentum, geopolitics), score the watchlist against the strategy set, distill 2-3 actionable trade ideas, and log it all to today's journal. Runs before the open — places NO orders. Use for "/pre-market", "run pre-market research", "draft today's trade ideas", or a scheduled pre-open trigger. Silent unless urgent.
---

# Pre-market — Phase 1: Research & draft

Recommended cron (America/New_York): `0 9 * * 1-5` (09:00 ET, before the 09:30 open).

This is the **research phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md` and
`references/strategy.md` and follow them — this skill is a phase-specific entry point, not a
replacement. `strategy.md` §0 is non-negotiable; nothing here overrides it.

This phase runs **before the open**, so the market is closed and **no order tool may be invoked**
(§0.5). The output is a researched, drafted candidate set that the `market-open` skill executes.

## Do this

Always run these four in order; the rest builds on them.

1. **Check the account** (`CLAUDE.md` preconditions). Confirm `config.toml` parses, the SOP
   universe list (`config.toml::sop_universe_list_name`) is fetchable from Robinhood, and
   there's no `KILL_SWITCH`. Read the **Robinhood balance and open positions** from
   the MCP: cash, total equity, every open position (ticker, qty, avg entry, current mark,
   unrealized P&L). If the MCP is unreachable, note it and continue with research only — this
   phase never orders. This snapshot anchors sizing and the goal check (beat the S&P 500).
2. **Research today's catalysts** via web search, in this order:
   - **Earnings** reporting today / this week (esp. watchlist or open positions).
   - **Economic data** on today's calendar (CPI, PPI, jobs, FOMC, PMI) with release times ET.
   - **Sector momentum** — which sectors are bid/offered pre-market and why.
   - **Geopolitical events** that could move the tape (conflict, elections, trade/tariff, energy).
   Capture each with a one-line summary + source link. Flag any catalyst on a held or watchlist
   ticker.
3. **Score the watchlist against the strategy set** (`references/strategy.md` §A —
   trend-following, momentum/breakout, RSI mean-reversion). For each ticker, note which
   strategies fire and the resulting tier (§3.1 sizing, §5 confluence bonus). Use the most
   recent daily OHLCV/quote data available pre-open.
4. **Find 2–3 actionable trade ideas.** Synthesize the catalyst research (step 2) with the
   strategy scores (step 3) into **2–3** concrete candidates — not more. Each must clear the
   5-question Decision Framework (`CLAUDE.md`), in writing, and respect the watchlist + caps.
   Prefer ideas where a catalyst and a strategy signal corroborate. If fewer than 2 survive, log
   that honestly — a thin day is data, not a reason to force trades.
5. **Log everything to the daily journal** `journal/{YYYY-MM-DD}.md` (`strategy.md` §7.2):
   - **Portfolio Status** — the step-1 balance + positions snapshot.
   - **Market Research** — the step-2 catalyst findings (Earnings / Economic Data / Sector
     Momentum / Geopolitical subsections, each with sources) plus one subsection per candidate
     considered, including skips and why.
   - **Draft Trade Ideas** — the 2–3 ideas from step 4, one pre-trade review line each
     (`ticker | thesis | strategy/catalyst | tier | indicative qty | indicative limit |
     max_loss`) marked `DRAFT — not executed`.
   - Leave Trades Executed / Positions Closed / Reflection as stubs for later phases.
6. **Do not** write to `trade-log.jsonl` (no pending entries pre-open) and **never** call an
   order tool.

## Notification policy: silent unless urgent

"Urgent" = a high-tier or confluence candidate fired, OR an open position is already at/through
its §0.3 trailing band and will need action at the open, OR a stop condition is live (`CLAUDE.md`
stop conditions). Otherwise stay silent.

When urgent, send one notification via `scripts/notify.sh`. The script reads `NTFY_TOKEN` from
the environment — set either as a routine/shell env var (cloud) or in `.env` (local; source it
first with `set -a; . ./.env; set +a` if the file exists). Only if `NTFY_TOKEN` is unset in the
environment, emit the message as the final session line instead.

```bash
# urgent — candidate or stop condition
./scripts/notify.sh -t "pre-market" -p 4 -T "chart_increasing" "<message>"

# non-urgent — end the session silently with a single quiet line (no notify call):
# "pre-market: nothing urgent — N candidates drafted."
```

## Report back (≤5 lines)

Account snapshot (equity + cash) · top catalysts today · the 2–3 actionable ideas · any urgent
flag · path to today's journal (nothing executes until the `market-open` phase).
