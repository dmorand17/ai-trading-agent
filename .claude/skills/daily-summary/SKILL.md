---
name: daily-summary
description: End-of-day phase of the AI Trading Agent SOP. Take an EOD portfolio snapshot, run the final trailing-stop sweep, write the End-of-Day Reflection, and recap the day from the trade log. Use for "/daily-summary", "end of day recap", "close out the journal", or a scheduled near-close trigger. Always sends one summary message.
---

# Daily summary — Phase 3: EOD snapshot & recap

Recommended cron (America/New_York): `55 15 * * 1-5` (15:55 ET, just before the close).

This is the **end-of-day phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md` and
`references/strategy.md` and follow them. `strategy.md` §0 is non-negotiable.

This phase is mostly **bookkeeping + protective tightening**, not new discovery. The late
session is the right hour to lock in gains before overnight risk.

## Do this

1. **Preconditions** (`CLAUDE.md`) — confirm market status; if still open, exits/tightening may
   be placed; if closed, queue exits for the next open (§0.5). Pull live cash + positions from
   the MCP for the snapshot.
2. **Final trailing-stop sweep** across the whole book (`strategy.md` §0.3, §4.3): update each
   `peak_mark`, recompute the tier band, and close anything where `current_mark ≤
   peak_mark × (1 − band)`.
3. **EOD portfolio snapshot** → refresh the **Portfolio Status** section of
   `journal/{YYYY-MM-DD}.md` with end-of-day cash, every open position (ticker + qty + avg
   entry), total equity, mode, market status.
4. **Write the End-of-Day Reflection** (`strategy.md` §7.2) — 2–4 sentences. Required even on
   no-trade days: record *why* nothing fired and what would change that.
5. **Day recap from the log** — read today's lines in `trade-log.jsonl` (group by `intent_id`,
   take latest) and summarize: orders placed, fills, exits with realized P&L, rejections. This
   is the single analytics source (§7.1).
6. Ensure Trades Executed / Positions Closed tables are complete (`None today.` if empty).

## Notification policy: always send one message

Send exactly **one** summary message every trading day, including no-trade days, via
`scripts/notify.sh`. The script reads `NTFY_TOKEN` from the environment — set either as a
routine/shell env var (cloud) or in `.env` (local; source it first with `set -a; . ./.env; set
+a` if the file exists). Only if `NTFY_TOKEN` is unset in the environment, emit as the final
session line instead.

```bash
./scripts/notify.sh -t "daily-summary" -p 3 -T "bar_chart" "<EOD recap ≤6 lines>"
```

## Report back (the one daily message, ≤6 lines)

Date + mode · EOD equity + cash · open positions (count) · trades today (placed/filled) ·
positions closed + realized P&L · path to today's journal.
