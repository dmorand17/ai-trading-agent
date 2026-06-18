---
name: portfolio-review
description: Portfolio-review phase of the AI Trading Agent SOP. Snapshot current holdings + unrealized P&L, compute account total return vs SPY since inception, and capture lessons through the Peter Lynch lens. Writes journal/portfolio-review.md (a single living ledger). Use for "/portfolio-review", "how's the book doing?", or a weekly check. Sends no notification.
---

# Portfolio review — Phase 4: Book health & lessons

This is the **portfolio-review phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md`
and `references/strategy.md` for context. This phase is **read-only over trade data** — it never
places orders and never edits `data/trade-log.jsonl` or the daily journals. (It does refresh the
`data/watchlist.json` cache and write its own ledger — neither is trade data.)

Cadence is **weekly or on-demand** (scheduled Friday after the close) — this is a low-trade-frequency
buy-and-hold account, so the review is framed around the *holdings* (which change slowly) rather
than per-trade activity. Useful from day one, even with zero closed trades.

## Do this

1. **Read the last-run timestamp** — read `data/last-portfolio-review.json` to get
   `last_run_utc`. If the file is missing, use `null` (treat as "all time").

   ```json
   { "last_run_utc": "2026-06-13T18:00:00Z" }
   ```

2. **Reconcile Robinhood orders since last run** — pull filled orders from the Robinhood MCP for
   the Agentic account (`get_equity_orders`, `state=filled`, `created_at_gte=last_run_utc`; omit
   `created_at_gte` when `last_run_utc` is null). For each filled order, check whether its
   `order_id` appears in any `mcp_response.order_id` field in `data/trade-log.jsonl`. Any order
   not found there was placed outside the SOP — back-fill it:
   - Append a line to `data/trade-log.jsonl` with `result: "filled"` and
     `"note": "back-filled from Robinhood order history; placed outside SOP"`.
   - Append / update `data/positions.jsonl` for the affected ticker (recompute `total_qty` and
     `avg_entry_price` against any existing position line for that ticker).
   - Tell the user what was back-filled (ticker · qty · price · date). If nothing is missing,
     say "trade-log is in sync."
   This reconciliation runs **before** the book snapshot so the snapshot reflects all fills.

3. **Refresh the watchlist cache** — force a refresh of `data/watchlist.json` from the Robinhood
   MCP per the `strategy.md` §2 policy (`get_watchlists` → `get_watchlist_items`, equity-filter,
   rewrite with a fresh `fetched_at_utc`). The weekly review is the standing refresh point that
   keeps the cache current. On a failed fetch, keep the existing cache and note staleness — do not
   halt.

4. **Snapshot the book** — read `data/positions.jsonl` for current open positions and refresh
   each one's unrealized P&L against a live quote. Note total equity and cash.

5. **Total return vs SPY since inception** — this is the project's whole goal (`CLAUDE.md`:
   beat the S&P 500). Compute the account's total return (realized + unrealized) from inception
   to now, and compare against SPY's total return over the same window. This is measurable from
   day one — do NOT gate it on having closed trades.

6. **Realized metrics when available** — from `data/trade-log.jsonl` (group by `intent_id`, take
   latest line per intent; closed sells carry `realized_pnl_usd`, `realized_return_pct`,
   `holding_period_days`): total realized P&L and win rate (closed sells with
   `realized_pnl_usd > 0` ÷ total closed). If nothing has closed yet, say so plainly — do not
   manufacture a win rate over zero trades.

7. **Lessons** — 3–5 bullets through the Peter Lynch lens, applied to *what you hold now*: are
   winners being let run; is any thesis deteriorating; is anything overextended; was anything
   sold too early. Pull frictions and near-misses from the daily journals since the last review.

8. **Write `journal/portfolio-review.md`** — a single **living file** (committed, not dated).
   Prepend the newest review at the top under a `## {YYYY-MM-DD}` heading so the file reads as a
   running ledger, newest-first. Sections per entry: Snapshot · Total Return vs SPY · Realized
   P&L (or "none closed yet") · Lessons · Reconciliation (list any back-filled trades, or "in sync").

9. **Update `data/last-portfolio-review.json`** — overwrite with the current UTC timestamp so
   the next run knows where to start its reconciliation window.

## Notification policy: none

This phase sends **no** push notification. It writes `journal/portfolio-review.md` and reports
back in-session only.

## Report back (≤6 lines)

Review date · reconciliation result (back-filled N trades or "in sync") · open positions +
unrealized P&L · total return vs SPY since inception · realized P&L + win rate (or "none closed
yet") · path to `journal/portfolio-review.md`.
