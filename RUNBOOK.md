# AI Trading Agent — Daily Runbook

The SOP runs as a sequence of Claude Code slash-command invocations. Each phase is a skill that
reads `CLAUDE.md` and `references/strategy.md` and follows those rules exactly. Nothing here
overrides `strategy.md §0`.

---

## Daily schedule (Mon–Fri, US market days only)

| Time (ET) | Phase | Slash command |
|---|---|---|
| 09:00 | Pre-market research | `/pre-market` |
| 09:35 | Execute trades | `/market-open` |
| Every 30 min, 10:00–15:30 | Intraday stop sweep | `/midday-sweep` |
| 15:55 | EOD snapshot & journal | `/daily-summary` |
| Friday 16:00 | Weekly recap | `/weekly-review` |
| Any time (market open) | User-directed trade | `/adhoc-trader` |

---

## Phase 1 — Pre-market (`/pre-market`)

**When:** 09:00 ET, before the open. Market is closed; no orders are placed.

**What it does:**
1. Reads account balance + open positions from Robinhood
2. Web-searches today's catalysts: earnings, economic data (CPI/FOMC/jobs/PMI), sector momentum, geopolitics
3. Scores the full watchlist against the three strategies (trend-following, momentum/breakout, RSI mean-reversion)
4. Distills 2–3 draft trade ideas with thesis, tier, indicative qty/limit, and day-1 max loss
5. Writes everything to `journal/YYYY-MM-DD.md` — marked `DRAFT — not executed`

**Halts if:** KILL_SWITCH present (MCP unreachable → continues research without account data)

**Notification:** Silent unless a high-tier or confluence candidate fired, or an open position is near its trailing-stop band.

**Output:** `journal/YYYY-MM-DD.md` (Portfolio Status + Market Research + Draft Trade Ideas sections)

### Sample prompts

```
/pre-market
```
```
Run pre-market research for today.
```
```
What should I be looking at before the open today?
```
```
Draft today's trade ideas.
```

---

## Phase 2 — Market-open (`/market-open`)

**When:** 09:35 ET, five minutes after the open.

**What it does:**
1. Verifies all hard preconditions (MCP connected, Agentic account, market open, `config.toml` valid, universe list fetchable, no KILL_SWITCH, `trade-log.jsonl` writable)
2. Loads draft candidates from today's journal; runs the full scoring loop from scratch if pre-market didn't run
3. For each candidate: sizes the position → answers the 5-question Decision Framework → spawns the risk-reviewer → writes `pending` to `trade-log.jsonl` → places the order
4. Sweeps all open positions for trailing-stop breaches on the same pass
5. Records `peak_mark = entry` in `positions.jsonl` for every new buy
6. Updates journal Trades Executed + Positions Closed tables

**Halts if:** Any precondition fails; market closed; daily loss cap breached.

**Notification:** Only if an order is placed or a trailing stop fires.

**Output:** `trade-log.jsonl` (new entries) · `positions.jsonl` (new peak_mark entries) · `journal/YYYY-MM-DD.md` (Trades Executed + Positions Closed filled)

### Sample prompts

```
/market-open
```
```
Execute today's trades.
```
```
Open the session and place any orders from the pre-market drafts.
```
```
Run the market-open phase.
```

---

## Phase 3 — Midday sweep (`/midday-sweep`)

**When:** Every 30 minutes, 10:00–15:30 ET. Sits between market-open and daily-summary.

**What it does:**
1. Reads `positions.jsonl` to reconstruct `peak_mark` per position
2. Pulls live quotes for held tickers only (not the full watchlist)
3. For each position: updates `peak_mark`, computes the trailing band (12% / 8% / 6% / 4% at <+15% / +15–24% / +25–49% / ≥+50% gain), closes on breach via limit at `bid × 0.998`
4. Also closes any position held ≥ 30 trading days (time stop)
5. Appends a row to today's journal Positions Closed only if something fired

**Does NOT:** Score the watchlist, open new positions, do any research.

**Halts if:** Market closed (exits cleanly, does nothing).

**Notification:** Silent unless an exit fires.

**Output:** `trade-log.jsonl` + `positions.jsonl` (only on an exit) · `journal/YYYY-MM-DD.md` Positions Closed row (only on an exit)

### Sample prompts

```
/midday-sweep
```
```
Check my trailing stops.
```
```
Sweep my open positions for stop breaches.
```
```
Run the intraday stop check.
```

---

## Phase 4 — Daily summary (`/daily-summary`)

**When:** 15:55 ET, just before the close.

**What it does:**
1. Final trailing-stop sweep across all positions (same logic as midday-sweep)
2. Refreshes the Portfolio Status section of today's journal with EOD cash + equity + open positions
3. Writes the End-of-Day Reflection (2–4 sentences — mandatory even on no-trade days)
4. Reads today's `trade-log.jsonl` lines and summarizes: orders placed, fills, exits, realized P&L, rejections
5. Ensures Trades Executed and Positions Closed tables are complete (`None today.` if empty)

**Notification:** Always sends exactly one summary message — every trading day, including no-trade days.

**Output:** `journal/YYYY-MM-DD.md` (Portfolio Status + EOD Reflection + completed tables)

### Sample prompts

```
/daily-summary
```
```
Run the end-of-day summary.
```
```
Close out today's journal.
```
```
Give me an EOD recap.
```

---

## Phase 5 — Weekly review (`/weekly-review`)

**When:** Friday at 16:00 ET, after the close. Read-only — never places orders or edits prior logs.

**What it does:**
1. Reads all daily journals for the Mon–Fri window
2. Computes from `trade-log.jsonl`: realized P&L by strategy and theme, win rate, exit-reason breakdown (trailing stop / time stop / manual), open positions + unrealized P&L
3. Compares net return vs SPY over the same window (the benchmark goal)
4. Writes 3–5 lesson bullets from the week's daily reflections
5. Suggests optional tuning changes for `strategy.md §A.4` knobs — suggestions only, never auto-applied
6. Creates `journal/YYYY-MM-DD-weekly-review.md` (Friday's date)

**Notification:** Always sends exactly one weekly summary message.

**Output:** `journal/YYYY-MM-DD-weekly-review.md`

### Sample prompts

```
/weekly-review
```
```
Run the weekly review.
```
```
How did the week go? Recap P&L, win rate, and lessons.
```
```
Weekly recap — compare against SPY and suggest any strategy tuning.
```

---

## On-demand — Adhoc trader (`/adhoc-trader`)

**When:** Any time the market is open. Human-in-the-loop — you direct the trade.

**What it does:** Executes a single user-specified trade through the same audit gates as the SOP loop (risk-reviewer, `trade-log.jsonl`, journal). Key differences from the autonomous loop:
- You choose the ticker, side (buy/sell), order type (limit/market), size, and price
- Sells are allowed (not just exits from §4.2 rules)
- Off-watchlist tickers are allowed — the ticker is added to the Agent WatchList automatically
- If the risk-reviewer rejects, it asks you whether to override rather than silently skipping

**Halts if:** Market closed (never queues — just tells you and stops).

**Required:** ticker + side. Optional at invocation: order type (defaults to limit), size, price — if missing, the skill pulls live market data and shows you bid/ask, SMAs, RSI, and a suggested limit price before asking.

### Sample prompts

```
/adhoc-trader NVDA buy
```
```
/adhoc-trader PLTR sell
```
```
Buy 10 shares of RKLB at a limit.
```
```
Sell half my AMD position.
```
```
I want to buy LUNR — show me the current price and suggest a limit.
```

---

## Key files

| File | Written by | Notes |
|---|---|---|
| `journal/YYYY-MM-DD.md` | pre-market (creates) → market-open → midday-sweep → daily-summary | One per trading day; mandatory even on no-trade days |
| `journal/YYYY-MM-DD-weekly-review.md` | weekly-review | One per week, Friday's date |
| `trade-log.jsonl` | market-open, midday-sweep, adhoc-trader | Append-only; the single analytics source |
| `positions.jsonl` | market-open, midday-sweep | Append-only; reconstruct state by taking latest line per `(ticker, entry_intent_id)` |
| `config.toml` | You (edit manually) | `mode`, `require_risk_review`, `cash_reserve_pct`, `block_tickers` |
| `themes.toml` | You + adhoc-trader (when adding tickers) | Must stay in sync with the Robinhood Agent WatchList |
| `KILL_SWITCH` | You (create/delete manually) | Presence halts all new entries; delete to re-enable |

---

## Quick-reference: stop conditions

Any of these halts the current phase and reports to you:

- Market is closed (orders halt; research and journal still run)
- Daily loss cap breached (`daily_loss_cap_pct` × equity, default 2%)
- MCP unreachable mid-loop
- KILL_SWITCH file present at repo root
- `config.toml` missing or unparseable
- Agent WatchList not found on Robinhood
- `trade-log.jsonl` unwritable

---

## Cron reference (optional automation)

```cron
# Pre-market research — 09:00 ET Mon–Fri
0 9 * * 1-5

# Market-open execution — 09:35 ET Mon–Fri
35 9 * * 1-5

# Midday stop sweep — every 30 min, 10:00–15:30 ET Mon–Fri
0,30 10-15 * * 1-5

# Daily summary — 15:55 ET Mon–Fri
55 15 * * 1-5

# Weekly review — 16:00 ET Friday
0 16 * * 5
```
