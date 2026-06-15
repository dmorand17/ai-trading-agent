# Time-State Policy

The US regular session behaves differently across its 6.5 hours. The same signal at 9:35 ET (chaotic price discovery) is not the same trade as at 15:35 ET (institutional accumulation). This file defines three discrete time states and the rule modifiers each one applies.

When `respect_time_state = true` in `mode.toml` (recommended default), every SOP loop pass first determines the current state and then applies the modifiers below on top of `references/rules.md`.

---

## 1. States

All times America/New_York. Computed against the live US/Eastern wall clock. Outside regular session, `state = "CLOSED"` and no orders fire (rule §0.5).

| State | Window | Character | New entries? |
| --- | --- | --- | --- |
| **A — Morning Discovery** | 09:30 – 10:30 | High volatility, wide spreads, fake-outs common. Overnight news still flowing through prints. | Yes, but smaller. |
| **B — Midday Drift** | 10:30 – 15:00 | Low volume, thin moves, easy to get chopped. | Restricted — only **high-tier** signals. |
| **C — Power Hour** | 15:00 – 16:00 | Institutional rebalancing, tight spreads, biggest single-session liquidity window. Closing tape is the cleanest read on "what does smart money think today?" | Yes. Standard sizing. Best execution. |
| **CLOSED** | otherwise | Market closed. | No orders, ever (§0.5). |

Implementation:

```python
# pseudocode — Trader resolves this at the top of every SOP loop pass
now_et = current_time(tz="America/New_York")
if market_holiday(now_et) or not weekday(now_et):
    state = "CLOSED"
elif now_et.time() < time(9,30) or now_et.time() >= time(16,0):
    state = "CLOSED"
elif now_et.time() < time(10,30):
    state = "A"
elif now_et.time() < time(15,0):
    state = "B"
else:
    state = "C"
```

The state goes into every `trade-log.jsonl` line as `time_state` and into the daily journal's Portfolio Status section.

---

## 2. State-A modifiers (Morning Discovery, 09:30 – 10:30)

The morning is for executing *pre-planned* entries fast, **not** chasing whatever just ran. Cluster signals computed overnight are exactly the kind of pre-plan State A is good for.

### 2.1 Sizing
- Multiply the tier-based size from `rules.md` §3.1 by **0.5**. A medium-tier 1.0% becomes 0.5%.
- Hard cap unchanged. Cash reserve unchanged.

### 2.2 Spread filter
- Widen the §4.1 spread filter from 50 bps to **100 bps**. The morning has structurally wider spreads; the standard filter would reject too many.

### 2.3 Limit price
- Standard `ask × 1.002`. Do **not** widen the slippage budget — if the print is running, the limit will fail and the SOP will re-evaluate next session. That's a feature: missing a chase trade is fine.

### 2.4 Fake-out detection
- Require **volume confirmation** before any State-A entry: 5-minute realized volume on the candidate ≥ 2× its 10-day average for that 5-minute bucket. The Trader pulls this from a quote source (Robinhood MCP if available, otherwise skip the entry rather than fudge it).
- If volume can't be verified, skip the trade and log `Decision: Skipped — State A volume confirmation unavailable`.

### 2.5 Trailing stop
- Keep the §4.3 trailing band wide. Do **not** ratchet the hard stop in State A even if `gain_pct` crosses +15% — the morning move may be a fake-out and you don't want to lock in break-even on a head-fake. The ratchet logic resumes in State B.
- This is the only place the time-state policy relaxes a rule from `rules.md`. Documented exception.

### 2.6 Exits
- All exits run normally. The −8% hard stop (§0.3) is sacred in every state.

---

## 3. State-B modifiers (Midday Drift, 10:30 – 15:00)

Midday is for **watching, not buying.** Most retail-noise moves happen here; institutional desks have stepped back; the tape is unreliable.

### 3.1 New entries restricted
- Only **high-tier** signals (score ≥ 80 for Signal A, ≥ 85 for Signal B; combined A+B always allowed). Everything else gets logged in the journal's Market Research section with `Decision: Held — State B blocks medium/low tiers`.

### 3.2 Sizing
- Standard tier-based size from `rules.md` §3.1. No multiplier.

### 3.3 Spread filter
- Standard 50 bps from §4.1.

### 3.4 Trailing stop
- Standard §4.3 logic, including the ratchet. State B is where the profit-protection trailing stop earns its keep.

### 3.5 Position monitoring
- Every open position is re-checked for the −8% hard stop and the trailing band on every loop pass.
- Re-check for any newly-published Form 4 `S` from a CEO/CFO of an open position (§4.2 "Insider sell kill").

---

## 4. State-C modifiers (Power Hour, 15:00 – 16:00)

The cleanest hour for execution. Volume surges, spreads tighten, the closing tape reflects institutional positioning.

### 4.1 Sizing
- Standard tier-based size. **Optional**: medium and high tiers may add `+0.25%` if the `time_state == "C"` setting is opted-in via `mode.toml::state_c_size_bump = true` (off by default; document in `mode.toml`).

### 4.2 Spread filter
- Tighten to **30 bps** (from 50 bps). Power Hour spreads are real; if a name still has a wide quote at 15:30 it's probably broken.

### 4.3 Limit price
- Standard `ask × 1.002`.

### 4.4 Trailing stop
- Re-evaluate **every open position** for trailing-band tightening. This is the right hour to lock in gains before overnight risk.

### 4.5 End-of-day prep
- At 15:50 — write the End-of-Day Reflection section of `journal/{today}.md` (§8.2 #5). Do not wait for after-hours.
- At 15:55 — final sweep of open positions for `S` codes from CEO/CFO insiders. Same logic as State B but explicit.

---

## 5. Routine scheduling implications

A single 9:35 daily routine misses the value of State C. Recommended cloud routine schedule for the SOP (cap-conscious — 4 runs/day):

| Cron (America/New_York) | State at trigger | What runs |
| --- | --- | --- |
| 09:35 | A | Full SOP loop. New entries from overnight cluster scans. State-A sizing. |
| 10:35 | B | State transition sweep. Scan open positions. Block most new entries. |
| 15:05 | C | Power-Hour entries. Trailing-stop tightening across the book. |
| 15:55 | C (end) | End-of-Day Reflection. Final stop-out sweep. Commit journal. |

If your daily routine cap is tight, drop the 10:35 sweep — State B positions are mostly monitored, not actioned.

---

## 6. mode.toml additions

```toml
respect_time_state = true        # honor the State A/B/C rules in references/time-state.md
state_c_size_bump = false        # opt-in: +0.25% to medium/high sizes during Power Hour
```

When `respect_time_state = false`, the SOP behaves as if every session minute is State B baseline (standard sizing, standard 50 bps spread, full tier mapping). Use only during dry-runs where you want consistent test results across the day.

---

## 7. trade-log.jsonl additions

Append two optional fields to the schema in `rules.md` §7.1:

| Field | When set | Notes |
| --- | --- | --- |
| `time_state` | always | `"A"`, `"B"`, `"C"`, or `"CLOSED"`. |
| `state_size_multiplier` | always | `0.5` in State A, `1.0` elsewhere (or `1.25` if `state_c_size_bump` and tier in {medium, high}). |

Analytics queries:

```sql
-- Win rate by time state
SELECT time_state, COUNT(*) AS n,
       AVG(CASE WHEN realized_pnl_usd > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
FROM trades
WHERE side='sell' AND result='filled'
GROUP BY time_state;
```

This is exactly the dataset you need to validate (or reject) the time-state policy after a few months of paper trading.

---

## 8. Validation

Before going live with `respect_time_state = true`:

1. Run paper mode for ≥ 30 trading days with all four scheduled runs (09:35 / 10:35 / 15:05 / 15:55).
2. Query the analytics above. If State A win-rate is significantly worse than State C, consider blocking new entries in State A entirely (set State-A `min_score_to_trade` higher).
3. If State B sees any executed trade that wasn't a high-tier signal, that's a bug — the Trader should have blocked it.
4. If `state_c_size_bump` is enabled, check the marginal trades it produced: did they actually improve P&L, or just add risk?

---

## 9. Interaction with the Risk Reviewer

The `risk-reviewer` subagent (`.claude/agents/risk-reviewer.md`) should be extended to check:

- `proposal.time_state` matches the wall clock when the proposal was created (within 5 minutes).
- Sizing in the proposal matches the State A/B/C rules above.
- State-B proposals are reject-by-default unless conviction tier is `high`.

These checks are added to the Reviewer's checklist as Section G when this policy goes live.
