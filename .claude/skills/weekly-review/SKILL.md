---
name: weekly-review
description: Weekly review phase of the AI Trading Agent SOP. Read the week's journals and trade log, compute P&L / win-rate by strategy and theme, capture lessons, and suggest tuning for the strategy knobs. Writes journal/{YYYY-MM-DD}-weekly-review.md. Use for "/weekly-review", "weekly recap", "how did the week go", or a scheduled Friday trigger. Always sends one summary message.
---

# Weekly review — Phase 4: Recap & lessons

Recommended cron (America/New_York): `0 16 * * 5` (16:00 ET Friday, after the close).

This is the **weekly review phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md`
and `references/strategy.md` for context. This phase is **read-only over trade data** — it never
places orders and never edits `trade-log.jsonl` or prior daily journals (§10: append an
`Addendum` rather than editing history).

## Do this

1. **Gather the week** — read `journal/{YYYY-MM-DD}.md` for each trading day in the current
   Mon–Fri window, and the full `trade-log.jsonl` (the single analytics source, `strategy.md`
   §7.1).
2. **Compute metrics** from `trade-log.jsonl` (group by `intent_id`, take latest line per
   intent; closed sells carry `realized_pnl_usd`, `realized_return_pct`, `holding_period_days`,
   `exit_reason`):
   - Total realized P&L for the week and per **strategy** (`signal_source`: trend / breakout /
     rsi_revert and confluence combos).
   - Total realized P&L per **theme** (`theme` field; look up `themes.toml` for any entries
     missing the field). Rank themes best → worst for the week.
   - Win rate (closed sells with `realized_pnl_usd > 0` ÷ total closed).
   - Exit-reason breakdown (trailing_stop / time_stop / manual).
   - Open positions carried into next week + unrealized P&L (grouped by theme).
   - **Benchmark check:** compare the week's net return (realized + unrealized) against SPY over
     the same window — the goal is to beat the S&P 500 (`CLAUDE.md`).
   - jq recipes are in `strategy.md` §7.1.
3. **Lessons** — 3–5 bullets: what worked, what didn't, near-misses or rule frictions surfaced
   in the daily reflections.
4. **Tuning suggestions** — concrete, optional knob changes for `references/strategy.md` §A.4
   (e.g. raise a `min_score_to_trade`, adjust `volume_confirm_mult` or `rsi_oversold`).
   **Suggest only** — never edit `strategy.md` or `config.toml` here; the user decides.
5. **Write `journal/{YYYY-MM-DD}-weekly-review.md`** where the date is the Friday of the week
   being reviewed. Create a new file each week (never append to prior weeks' files). Sections:
   Summary · P&L by Strategy · P&L by Theme · vs SPY Benchmark · Exit Reasons · Open Positions
   Carried (by theme) · Lessons · Tuning Suggestions.

## Notification policy: always send one message

Send exactly **one** weekly summary message via `scripts/notify.sh`. The script reads
`NTFY_TOKEN` from the environment — set either as a routine/shell env var (cloud) or in `.env`
(local; source it first with `set -a; . ./.env; set +a` if the file exists). Only if `NTFY_TOKEN`
is unset in the environment, emit as the final session line instead.

```bash
./scripts/notify.sh -t "weekly-review" -p 3 -T "calendar" "<weekly recap ≤6 lines>"
```

## Report back (the one weekly message, ≤6 lines)

Week range · realized P&L (total + best/worst strategy) · win rate · trades count · vs SPY ·
path to `journal/{YYYY-MM-DD}-weekly-review.md`.
