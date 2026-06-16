---
name: portfolio-review
description: Portfolio-review phase of the AI Trading Agent SOP. Snapshot current holdings + unrealized P&L, compute account total return vs SPY since inception, and capture lessons through the Peter Lynch lens. Writes journal/portfolio-review.md (a single living ledger). Use for "/portfolio-review", "how's the book doing?", or a monthly check. Sends no notification.
---

# Portfolio review — Phase 4: Book health & lessons

This is the **portfolio-review phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md`
and `references/strategy.md` for context. This phase is **read-only over trade data** — it never
places orders and never edits `data/trade-log.jsonl` or the daily journals.

Cadence is **on-demand or monthly**, not weekly — this is a low-trade-frequency buy-and-hold
account, so the review is framed around the *holdings* (which change slowly) rather than a
calendar week (which is mostly noise). Useful from day one, even with zero closed trades.

## Do this

1. **Snapshot the book** — read `data/positions.jsonl` for current open positions and refresh
   each one's unrealized P&L against a live quote. Note total equity and cash.
2. **Total return vs SPY since inception** — this is the project's whole goal (`CLAUDE.md`:
   beat the S&P 500). Compute the account's total return (realized + unrealized) from inception
   to now, and compare against SPY's total return over the same window. This is measurable from
   day one — do NOT gate it on having closed trades.
3. **Realized metrics when available** — from `data/trade-log.jsonl` (group by `intent_id`, take
   latest line per intent; closed sells carry `realized_pnl_usd`, `realized_return_pct`,
   `holding_period_days`): total realized P&L and win rate (closed sells with
   `realized_pnl_usd > 0` ÷ total closed). If nothing has closed yet, say so plainly — do not
   manufacture a win rate over zero trades.
4. **Lessons** — 3–5 bullets through the Peter Lynch lens, applied to *what you hold now*: are
   winners being let run; is any thesis deteriorating; is anything overextended; was anything
   sold too early. Pull frictions and near-misses from the daily journals since the last review.
5. **Write `journal/portfolio-review.md`** — a single **living file** (committed, not dated).
   Prepend the newest review at the top under a `## {YYYY-MM-DD}` heading so the file reads as a
   running ledger, newest-first. Sections per entry: Snapshot · Total Return vs SPY · Realized
   P&L (or "none closed yet") · Lessons.

## Notification policy: none

This phase sends **no** push notification. It writes `journal/portfolio-review.md` and reports
back in-session only.

## Report back (≤6 lines)

Review date · open positions + unrealized P&L · total return vs SPY since inception · realized
P&L + win rate (or "none closed yet") · path to `journal/portfolio-review.md`.
