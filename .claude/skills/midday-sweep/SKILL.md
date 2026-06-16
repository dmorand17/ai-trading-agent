---
name: midday-sweep
description: Lightweight intraday trailing-stop sweep for the AI Trading Agent SOP. Runs the §0.3 tiered trailing stop (and the §4.2 time stop) across all open positions and closes any breach — nothing else. No scoring, no new entries, no research. Use for "/midday-sweep", "sweep my positions", "check the trailing stops", or a scheduled intraday trigger between market-open and daily-summary. Messages only if an exit fires.
---

# Midday sweep — lightweight intraday stop check

Recommended cron (America/New_York): `0,30 10-15 * * 1-5` (every 30 min, 10:00–15:30 ET — sits
between the 09:35 `market-open` and 15:55 `daily-summary` sweeps).

This is the **protective-exit-only** phase. It exists to close the intraday gap: without it, an
open position is only checked at ~09:35 and ~15:55. Read `strategy.md` §0.3 (trailing stop) and
§4.2/§4.3 (exits + mechanics) — that's the only logic this skill runs. **It never opens a
position, never scores the watchlist, and never researches catalysts.**

## Do this

1. **Minimal preconditions.** MCP connected (`tools/list` shows order tools) · account is the
   **Agentic** account · `trade-log.jsonl` + `positions.jsonl` writable · no `KILL_SWITCH`.
   Check **market status**: if **closed**, do nothing but log a one-line note and exit (a stop
   observed while closed is handled by the next open per §0.5 — this skill does not queue).
   Skip the full universe-list / config validation the other phases do; you place no entries, so
   the universe is irrelevant.
2. **Read trailing state.** Reconstruct each open position's `peak_mark` from `positions.jsonl`
   (latest line per `ticker × entry_intent_id`). Pull live positions (`get_equity_positions`) and
   quotes (`get_equity_quotes`) for the held symbols only — one batched quote call, not the whole
   watchlist.
3. **Sweep (§0.3).** For each open position:
   - `peak_mark = max(peak_mark, current_mark)` → append the updated `peak_mark` to
     `positions.jsonl`.
   - `gain_pct = (peak_mark − entry_price) / entry_price` → look up the band (12% / 8% / 6% / 4%
     at <+15% / +15–24% / +25–49% / ≥+50%).
   - If `current_mark ≤ peak_mark × (1 − band)` → **close immediately**: write the `pending`
     `trade-log.jsonl` line first (§7), then place a closing **limit** at `bid × 0.998`
     (`time_in_force=gfd`, `regular_hours`) — never market for exits. Append the closing line with
     the sell-only fields (`entry_intent_id`, `realized_pnl_usd`, `realized_return_pct`,
     `holding_period_days`, `exit_reason: "trailing_stop"`).
4. **Time stop (§4.2), same pass.** If a position has been held ≥ 30 trading days, close it the
   same way with `exit_reason: "time_stop"`. (One date comparison — cheap, and it's a real exit.)
5. **Mode.** In `paper`, log `result: "paper"` and place no order. In `live`, place the closing
   limit (honor `block_tickers`).
6. **Journal — touch only if something fired.** If an exit closed, append a row to today's
   `journal/{YYYY-MM-DD}.md` **Positions Closed** table. Do **not** rewrite Portfolio Status,
   Market Research, or the reflection — `daily-summary` owns those. If the journal doesn't exist
   yet, create it with the standard headers and `None today.` stubs, then fill the closed row.

## Notification: only if an exit fires

No breach → stay silent (no message, no journal churn). On an exit, send one notification via
`scripts/notify.sh` (read `.env` for `NTFY_TOKEN`; fall back to the final session line if unset).

```bash
./scripts/notify.sh -t "midday-sweep" -p 4 -T "warning" "AMD trailing stop fired — sold 12 @ $156.30 (−$84)"
```

## Report back (≤3 lines)

Positions swept (count) · exits fired (ticker · reason · qty · price · realized P&L) or "no
breaches" · paths to `trade-log.jsonl` / journal if anything changed.
