---
name: market-research
description: Research & context phase of the AI Trading Agent SOP. Check Robinhood balance + open positions, web-search today's catalysts (earnings, economic data, sector momentum, geopolitics), surface anything relevant to held or watchlist tickers, and log it to today's journal. Places NO orders. Run before the open or any time you want a market brief. Use for "/market-research", "run market research", or "what should I be watching today". Silent unless urgent.
---

# Market research — Phase 1: Research & context

This is the **research phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md` and
`references/strategy.md` and follow them — this skill is a phase-specific entry point, not a
replacement. `strategy.md` §0 is non-negotiable.

This phase gives the user the context to decide what to trade (the user picks the trades — a
programmatic screener is a roadmap item). It **places no orders** — run it before the open, or
any time you want a market brief.

## Do this

1. **Check the account & resolve the universe** (`CLAUDE.md` preconditions). Confirm
   `config.toml` parses and there's no `KILL_SWITCH`. Resolve the SOP universe per the
   **`strategy.md` §2 refresh policy**: read the cache `data/watchlist.json` by default; refresh
   from the MCP (`get_watchlists` → `get_watchlist_items`, equity-filter, rewrite the cache) only
   if the user asked to refresh or the cache is missing (the weekly `portfolio-review` is the
   standing refresh point). On a failed refresh, fall back to the cache. Read the **Robinhood
   balance and open positions** from the
   MCP: cash, total equity, every open position (ticker, qty, avg entry, current mark, unrealized
   P&L). If the MCP is unreachable, note it and continue with research only (use the cached
   universe).
2. **Research today's catalysts** via web search, in this order:
   - **Earnings** reporting today / this week (esp. watchlist or open positions).
   - **Economic data** on today's calendar (CPI, PPI, jobs, FOMC, PMI) with release times ET.
   - **Sector momentum** — which sectors are bid/offered pre-market and why.
   - **Geopolitical events** that could move the tape.
   Capture each with a one-line summary + source link. Flag any catalyst on a held or watchlist
   ticker.
3. **Surface anything notable on held positions or the watchlist** — a position with news, a
   watchlist name with a catalyst, anything that informs the user's decisions today. Apply the
   Peter Lynch lens: flag deteriorating theses on winners worth holding, not just entries.
4. **Log to the daily journal** `journal/{YYYY-MM-DD}.md` (`strategy.md` §5.2) — keep it concise:
   - **Portfolio Status** — the step-1 balance + positions snapshot.
   - **Market Research** — 3–6 catalyst bullets (Earnings / Economic Data / Sector Momentum /
     Geopolitical, each one line + source), limited to held or watchlist names, plus at most 1–2
     short candidate notes (ticker · why · indicative size). **No full-universe scoring table and
     no multi-paragraph deep-dives in the journal** (§5.2); if a programmatic score is ever run,
     its table belongs in a gitignored `data/` file. Don't add a separate "Draft Trade Ideas"
     section — fold ideas into Market Research.
   - Leave Trades Executed / Positions Closed / Reflection as stubs for `stock-trader`.
5. **Do not** write to `data/trade-log.jsonl` and **never** call an order tool.

## Notification policy: silent unless urgent

"Urgent" = a catalyst materially affecting a held position, or a live stop condition (`CLAUDE.md`).
Otherwise stay silent.

When urgent, send one notification via `scripts/notify.sh`. 

```bash
./scripts/notify.sh -t "market-research" -p 4 -T "chart_increasing" "<message>"
```

## Report back (≤5 lines)

Account snapshot (equity + cash) · top catalysts today · anything notable on held/watchlist names
· any urgent flag · path to today's journal.
