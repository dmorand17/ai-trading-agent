# AI Trading Agent SOP

A Claude Code skill that runs a daily Standard Operating Procedure for US-equity trading via the [Robinhood Agentic Trading MCP](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).

The agent makes trade decisions from two (eventually three) independent cluster signals:

- **Signal A — Politician clusters** — multiple members of Congress filing buys of the same ticker in a tight window.
- **Signal B — Insider clusters** — multiple Section-16 insiders (CEO/CFO/Director/10% owner) filing Form 4 open-market purchases (code `P`) in a tight window.
- **Signal C — Social media (draft, not active)** — bullish-mention spikes across Reddit / Twitter / StockTwits. See [`references/social-signal.md`](references/social-signal.md).

The skill is a **set of markdown files** — there is no application code in this repo. The Claude Code session is the executor at runtime.

## File layout

```
.
├── SKILL.md                          ← Always-loaded dispatcher
├── README.md                         ← (this file)
├── mode.toml                         ← User-edited: paper vs live, allowlist, manual-confirm
├── watchlist.json                    ← User-edited: universe + per-symbol caps + cash reserve
├── KILL_SWITCH                       ← (create to halt; delete to resume)
├── trade-log.jsonl                   ← Append-only audit log (analytics source)
├── journal/
│   └── YYYY-MM-DD.md                 ← One markdown journal per trading day
├── positions.jsonl                   ← Trailing-stop state (peak_mark per open position)
└── references/
    ├── data-sources.md               ← All upstream data feeds
    ├── politician-signal.md          ← Signal A scoring
    ├── insider-signal.md             ← Signal B scoring
    ├── social-signal.md              ← Signal C — DRAFT, not yet active
    ├── sec-edgar-form4.md            ← Form 4 XML schema + discovery
    └── rules.md                      ← Mode, sizing, exits, kill switch, log schemas, analytics
```

## Configuration files

The SOP reads two config files at repo root on every invocation. Both are user-edited; the SOP never writes to them.

### `mode.toml`

Controls execution mode and risk caps. Full schema in `references/rules.md` §1.1.

```toml
mode = "paper"                     # "paper" | "live"
live_allowlist = []                # empty = all; ["AAPL"] = only AAPL trades go live
require_manual_confirm = true      # pause for "yes" before every live order
block_tickers = []
daily_loss_cap_pct = 0.02
max_cluster_exposure_pct = 0.25
max_ticker_exposure_pct = 0.05
```

### `watchlist.json`

Defines the trading universe, per-symbol allocation caps (overriding the 5% default), and the cash reserve floor. Full schema in `references/rules.md` §2.

```json
{
  "watchlist": [
    { "symbol": "SPY",  "description": "S&P 500 ETF — baseline market exposure",   "max_allocation_pct": 15 },
    { "symbol": "QQQ",  "description": "Nasdaq ETF — tech sector exposure",          "max_allocation_pct": 10 },
    { "symbol": "NVDA", "description": "GPU/AI infrastructure — high conviction",   "max_allocation_pct":  8 },
    { "symbol": "AAPL", "description": "Large cap tech — stability anchor",          "max_allocation_pct":  8 },
    { "symbol": "MSFT", "description": "Cloud/enterprise — AI infrastructure play",  "max_allocation_pct":  8 }
  ],
  "cash_reserve_pct": 20
}
```

### `.env` (gitignored — for upstream API keys only)

Robinhood MCP auth is handled by the connector itself and does **not** belong here. Only put third-party data-source keys here.

```bash
SEC_USER_AGENT="Your Name your.email@example.com"   # required by SEC fair-access policy
QUIVER_API_KEY=...                                   # optional: politician fallback
FINNHUB_API_KEY=...                                  # optional: politician fallback
```

## Prerequisites

1. **Robinhood Agentic account** (separate from your primary individual account). Up to 10 per user. Onboard via desktop. See the [Robinhood Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).
2. **Robinhood MCP connector installed** in Claude Code:
   - Endpoint: `https://agent.robinhood.com/mcp/trading`
   - Transport: HTTP
   - Install via Claude Code's connectors UI or in `~/.claude/.mcp.json`.
3. **SEC `User-Agent`** set (`SEC_USER_AGENT` in `.env`). SEC blocks default Python/curl agents.
4. **`mode.toml` and `watchlist.json`** present and valid at repo root.
5. **`.gitignore`** that excludes `.env`, `trade-log.jsonl`, `journal/`, `positions.jsonl`.

## Standalone signal scanner

For dry-runs and validating the methodology without involving Claude, run the standalone Form 4 scanner:

```bash
export SEC_USER_AGENT="Your Name your@email.com"   # required by SEC fair-access policy
python3 scripts/scan_form4.py                       # default: 100 most recent filings
python3 scripts/scan_form4.py --count 100 -v        # verbose: print every XML fetch
python3 scripts/scan_form4.py --no-write            # stdout only
```

Output: stdout summary + `signals/form4-{YYYY-MM-DD}.json` with the structured cluster data. Stdlib only — no `pip install`. Read-only — does **not** call the Robinhood MCP or touch the trade log.

The scanner implements Signal B's cluster definition (`references/insider-signal.md` §3) and scoring (§4): ≥2 distinct insiders, weighted count ≥ 4.0, ≥ $100K aggregate, code P only. Use it to (a) sanity-check the SOP's daily output against the same data, and (b) backfill historical days via the EDGAR daily-index (v2 — not yet implemented).

Expected baseline: **most days produce zero qualifying clusters.** Form 4 activity is dominated by routine compensation (codes A, M, F); a real cluster of open-market buys is rare and informative.

## Running the SOP interactively

From a Claude Code session **with this repo as the working directory**:

```
> Run the SOP
> Scan today's clusters
> Check Form 4 filings
> What should I trade today?
```

The skill auto-activates from those prompts. It will:

1. Check preconditions (MCP up, account is Agentic, market open, configs valid, no kill switch).
2. Pull Signal A and Signal B for today.
3. Score, apply the 5-question Decision Framework, size positions.
4. Write a `pending` line to `trade-log.jsonl` for each candidate.
5. Either skip the MCP (paper) or place a limit order (live, possibly behind a confirm prompt).
6. Update `journal/YYYY-MM-DD.md` and `trade-log.jsonl` with final state.
7. Scan open positions for the −8% hard stop and the profit-protection trailing stop.

## Automating with a Claude Code routine

Claude Code routines run your SOP on a schedule from Anthropic-managed cloud infrastructure, so they keep working when your laptop is closed. Routines are in research preview on Pro / Max / Team / Enterprise with Claude Code on the web enabled. See the [routines documentation](https://code.claude.com/docs/en/routines).

### One-time setup

1. Push this repo to a GitHub repository.
2. Connect that repository to Claude Code on the web (`/web-setup` from the CLI, or follow the prompts when creating the routine).
3. Add the **Robinhood Agentic Trading** MCP connector to your claude.ai account at [Settings → Connectors](https://claude.ai/customize/connectors). Routines can use any connector you've connected to your claude.ai account — connectors installed locally via `claude mcp add` are not visible to routines.
4. (Optional) Add Quiver / Finnhub / SEC `User-Agent` as environment variables on the cloud environment you'll attach to the routine.

### Create the routine

From the CLI in this repo:

```text
/schedule daily SOP run at 9:35 ET — read SKILL.md and run the daily loop
```

Or, equivalently, from the web at [claude.ai/code/routines](https://claude.ai/code/routines), click **New routine**.

Recommended routine config:

| Field | Value |
| --- | --- |
| Name | `Daily Trading SOP` |
| Prompt | See below |
| Repositories | This repo |
| Environment | Default (Trusted) is fine; add `SEC_USER_AGENT`, `QUIVER_API_KEY` etc. as env vars |
| Connectors | **Robinhood Agentic Trading** (required). Others optional. |
| Triggers (recommended — time-state aware) | See table below |

**Time-state-aware schedule** (per `references/time-state.md`). Each trigger fires the same routine; the SOP resolves its own state and applies the right modifiers:

| Cron (America/New_York) | State at trigger | What runs |
| --- | --- | --- |
| **09:35 weekdays** | A — Morning Discovery | Full SOP loop. Overnight cluster signals execute with **State A sizing (0.5×)** and wider spread filter. |
| **10:35 weekdays** | B — Midday Drift | Position sweep. Hard-stop ratchet resumes. New entries gated to **high-tier only**. |
| **15:05 weekdays** | C — Power Hour | Best execution window. Trailing-stop tightening across the book. Standard sizing. |
| **15:55 weekdays** | C (end) | End-of-Day Reflection + final stop-out sweep + journal commit. |

If your daily routine cap is tight, drop the 10:35 trigger — State B is mostly monitoring. Single-trigger fallback: just **09:35** (loses the Power Hour edge).

**Prompt (paste into the routine):**

```text
Activate the ai-trading-agent skill (loads SKILL.md from this repo). Execute the
daily SOP loop end-to-end:

1. Verify all hard preconditions (SKILL.md §3). Halt with a written reason if any
   precondition fails — do not place trades on a partial check.
2. Resolve the current time state (A/B/C/CLOSED) per references/time-state.md
   §1. Apply the state's sizing multiplier, spread filter, and entry gate.
3. Refresh Signal A (politicians) and Signal B (insiders) per references/
   politician-signal.md and references/insider-signal.md.
4. For each candidate, answer the 5-question Decision Framework (SKILL.md §5)
   in writing in the journal.
5. Honor mode.toml: paper today unless mode = "live".
6. If require_risk_review = true: spawn the risk-reviewer subagent with the
   proposal (.claude/agents/risk-reviewer.md). Only proceed on "approve".
7. Write trade-log.jsonl entries BEFORE any MCP order tool call. Include
   time_state and state_size_multiplier.
8. Place orders (or paper-log them) per references/rules.md.
9. Scan open positions for the −8% hard stop AND the profit-protection trailing
   stop (rules.md §0.3 and §4.3). Close on breach.
   - Skip the §4.3 hard-stop ratchet in State A (time-state.md §2.5).
10. Update journal/{today}.md with all required sections, including
    End-of-Day Reflection. Commit the journal entry and trade-log line to a
    claude/* branch and open a PR back to main.

Stop conditions and safety rules in SKILL.md §2 and §8 are non-negotiable —
do not override them.
```

### Additional triggers (optional)

- **Mid-day check (12:15 ET):** second scheduled trigger on the same routine, scoped to "scan open positions only, write any required exits, update today's journal".
- **End-of-day (16:05 ET):** third scheduled trigger to write End-of-Day Reflection and commit.
- **API trigger:** wire your phone or a Slack slash-command to `/fire` the routine ad-hoc. See routine docs for the bearer-token flow.

### Routine safety notes

- The routine runs **autonomously**, with no approval prompts during the run. The trade-log + Decision Framework + `mode.toml` `require_manual_confirm` are the only gates between the cloud session and a live Robinhood order.
- Keep `mode = "paper"` for the first ≥ 30 trading days of routine operation. Read the journal entries and trade-log analytics before flipping live.
- A routine running in the cloud can push to `claude/*`-prefixed branches by default. The journal commits will land on those branches; you'll see them as PRs to review locally.
- The cloud environment uses Trusted network access by default. SEC.gov and Robinhood's MCP are both reachable from the trusted allowlist; if you add a custom data source (e.g. CapitolTrades scraping), you may need to widen the network policy. See the [environment docs](https://code.claude.com/docs/en/claude-code-on-the-web#network-access).
- Routines count against your account's daily run cap. A 9:35 / 12:15 / 16:05 schedule uses ≤ 3 runs per trading day.

## Local automation alternatives

If you'd rather run on your own machine instead of in the cloud:

- **`/loop` in an open CLI session** — `loop` skill at 30m or 60m intervals during market hours. Useful for first-day shakedowns.
- **Desktop scheduled tasks** — Claude Desktop has a "Local" routine option that runs on your machine via the Desktop app's scheduler.
- **macOS LaunchAgent / cron** — run `claude -p "Run the SOP"` from a launchd plist or a cron line. Requires your laptop to be on and the CLI to be authenticated.

The hard requirement either way is that **the Robinhood MCP connector is reachable from wherever the SOP runs**.

## Analytics

`trade-log.jsonl` is the single source of truth for every trade across every day. Quick recipes:

```bash
# Latest state per intent
jq -s 'group_by(.intent_id) | map(max_by(.timestamp_utc))' trade-log.jsonl

# Total realized P&L on closed sells
jq -s '[.[] | select(.side=="sell" and .result=="filled") | .realized_pnl_usd // 0] | add' trade-log.jsonl
```

```sql
-- DuckDB
CREATE VIEW trades AS SELECT * FROM read_json_auto('trade-log.jsonl');
SELECT signal_source, SUM(realized_pnl_usd) AS pnl, COUNT(*) AS n
FROM trades WHERE side='sell' AND result='filled'
GROUP BY signal_source;
```

See `references/rules.md` §7.3 for the full analytics section.

## Stopping the SOP

- **One trade refused:** edit `mode.toml`, set `require_manual_confirm = true`. Next run will pause.
- **All new orders halted (existing exits keep running):** create an empty file named `KILL_SWITCH` at repo root.
- **Routine paused:** toggle the routine's `Repeats` switch at [claude.ai/code/routines](https://claude.ai/code/routines).
- **Routine deleted:** delete from the same page. Past sessions remain in your session list.

## Reading the skill

If you want to understand what the agent does without running it:

1. Read `SKILL.md` — the dispatcher.
2. Read `references/rules.md` — the canonical rules, including the non-negotiables in §0.
3. Read one signal file (`references/insider-signal.md` is the most mechanical).

Each reference file is self-contained and tunable at the bottom (`[signal_a]`, `[signal_b]` knobs).

## Roadmap / Ideas

Loose list of things that aren't built yet. Pull from the top.

### 1. ~~Two-agent split — Trader + Risk Reviewer~~ ✅ Built

Trader (main session running `SKILL.md`) spawns the `risk-reviewer` subagent (`.claude/agents/risk-reviewer.md`) before every MCP order call. Reviewer does pure rule-checking against `references/rules.md` §0, the watchlist, mode.toml, and the trade log. Binary approve/reject. Toggle: `require_risk_review = true` in `mode.toml`. Full design in `references/risk-review.md`.

Open follow-ups (not yet built):

- Two-routine cloud variant (Routine A writes proposals/, Routine B reviews on PR event). Documented in `references/risk-review.md` §9.
- Allowing the Reviewer to *propose* exits when it spots a Form 4 sale that the Trader missed.

### 2. Activate Signal C (social media)

See `references/social-signal.md`. Pick one source (ApeWisdom is easiest), run in parallel with A and B for ≥ 30 trading days, then flip `signal_c.active = true` in `mode.toml`.

### 3. Backtest harness

A read-only mode that replays historical Form 4 + politician PTR data against the current rules, producing a hypothetical `trade-log.jsonl`. Validates rule changes before they affect real money. Probably its own skill in a sibling repo.

### 4. Periodic rebalance against `watchlist.json`

If a watchlist symbol is *below* its `max_allocation_pct` for ≥ N weeks and the signal layer hasn't produced an entry, optionally top up to a configurable floor. Decision: separate skill, or `mode.toml` toggle?

### 5. Earnings + insider-window calendar

Block entries in the 5 trading days before earnings; block insider-signal entries inside the SEC trading blackout window. Both are knowable in advance from EDGAR + the issuer's IR calendar.

### 6. Slack / push notification on every live order

Optional MCP connector that posts pre-trade review + post-fill confirmation to a private Slack channel. Useful as a secondary audit trail and an "I'm awake" signal when the routine is autonomous.

### 7. Weekly summary routine

A second routine that runs Saturday morning, reads the week's `journal/*.md` and `trade-log.jsonl`, and writes a one-page weekly review with P&L by signal source, win rate, and tuning suggestions for the knobs in `politician-signal.md` / `insider-signal.md`.

### 8. Position-state file

`positions.jsonl` for trailing-stop state (`peak_mark`, active tier) is referenced in `rules.md` §4.3 but doesn't exist yet. Spec it and have the SOP write/read it.

### 9. Signal-quality metrics dashboard

Compute hit rate, average forward return at 5/10/30 days, and decay curve per signal source. Useful for deciding whether to deprecate a source or tighten its thresholds.

---

## Disclaimer

This is documented decision logic, not financial advice. The hard cap in `rules.md` §0.1, the per-symbol limits in `watchlist.json`, and the cash reserve in `watchlist.json` are user-settable; pick conservative levels and start in paper mode.
