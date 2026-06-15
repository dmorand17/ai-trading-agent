# AI Trading Agent SOP

A Claude Code Standard Operating Procedure for US-equity trading via the [Robinhood Agentic
Trading MCP](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).

The agent generates trade candidates from a small set of **classic, price-based strategies**
computed from daily OHLCV and quotes:

- **Trend-following** — buy strength already trending (`close > SMA20 > SMA50`).
- **Momentum / breakout** — buy a clean breakout above a 20-day base on expanding volume.
- **RSI mean-reversion** — buy a temporary oversold dip *within* an established uptrend.

Each strategy scores 0–100; the best firing score sets the conviction tier, and when two or more
fire on the same ticker the conviction upgrades one tier (confluence). Full mechanics in
[`references/strategy.md`](references/strategy.md) §A.

The SOP is a **set of markdown files** — there is no application code in this repo. The Claude
Code session is the executor at runtime. `CLAUDE.md` is the always-loaded dispatcher.

## File layout

```
.
├── CLAUDE.md                         ← Always-loaded dispatcher: goal, rules, daily loop
├── README.md                         ← (this file)
├── config.toml                       ← User-edited: mode, caps, universe pointer
├── themes.toml                       ← Ticker → theme mapping for P&L analytics
├── KILL_SWITCH                       ← (create to halt new orders; delete to resume)
├── trade-log.jsonl                   ← Append-only audit log (single analytics source)
├── positions.jsonl                   ← Trailing-stop state (peak_mark per open position)
├── journal/
│   ├── YYYY-MM-DD.md                 ← Daily journal (one per trading day)
│   └── YYYY-MM-DD-weekly-review.md   ← Weekly review (written each Friday)
├── scripts/
│   └── notify.sh                     ← ntfy push notifications
├── references/
│   ├── strategy.md                   ← Strategies, sizing, exits, mode, log schemas (canonical)
│   ├── risk-review.md                ← Two-agent risk-review flow
│   └── robinhood-mcp.md              ← Robinhood MCP tool reference
└── .claude/
    ├── agents/
    │   └── risk-reviewer.md          ← Adversarial rule-check subagent
    └── skills/                       ← Phase entry points (pre-market, market-open, …)
```

> The original cluster-signal engine (congressional buys, insider Form 4) and the time-state
> policy live in `_archived/` for reference. They are not part of the active SOP.

## Configuration

### `config.toml`

Controls execution mode, safety gates, and the universe pointer. Full schema in
`references/strategy.md` §1.1.

```toml
mode = "paper"                              # "paper" | "live"
block_tickers = []                          # global blocklist, overrides everything
daily_loss_cap_pct = 0.02                   # halt new entries when day P&L ≤ −this × equity
cash_reserve_pct = 0.10                     # minimum cash floor as a fraction of equity
sop_universe_list_name = "Agent WatchList"  # Robinhood watchlist used as the universe
discovery_mode = false                      # true = no universe filter (paper only)
require_risk_review = true                  # risk-reviewer gates every order; MANDATORY in live
```

### `themes.toml`

Maps every ticker in the Agent WatchList to one of eleven investment themes (nuclear, robotics,
space, ai, data_centers, cybersecurity, semiconductors, quantum_computing, defense_tech,
clean_energy, biotech). The `theme` field in `trade-log.jsonl` is populated from here; keep it
in sync whenever the Robinhood watchlist is modified.

### `.env` (gitignored)

Robinhood MCP auth is handled by the connector itself. Only third-party keys (e.g. the ntfy
push-notification token) go here. See `.env.example`.

## Prerequisites

1. **Robinhood Agentic account** (separate from your primary individual account). Up to 10 per
   user. Onboard via desktop. See the [Robinhood Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).
2. **Robinhood MCP connector installed** in Claude Code:
   - Endpoint: `https://agent.robinhood.com/mcp/trading`
   - Transport: HTTP
   - Install via Claude Code's connectors UI or in `~/.claude/.mcp.json`.
3. **`config.toml`** present and valid at repo root (create from the schema above).
4. **Agent WatchList** created on Robinhood (display name must match `sop_universe_list_name`).
5. **`.gitignore`** that excludes `.env`, `trade-log.jsonl`, `journal/`, `positions.jsonl`.

## Running the SOP interactively

From a Claude Code session **with this repo as the working directory**:

```
> Run the SOP
> What should I trade today?
> Scan the watchlist
> Review the trade log
```

`CLAUDE.md` (the dispatcher) is always loaded, so the agent knows the goal, the non-negotiable
rules, and the daily loop. It will:

1. Check preconditions (MCP up, account is Agentic, market open, configs valid, no kill switch).
2. Pull the Agent WatchList from Robinhood and score each ticker against the three strategies.
3. Apply the 5-question Decision Framework, size positions.
4. Write a `pending` line to `trade-log.jsonl` for each candidate.
5. Either skip the MCP (paper) or place a limit order (live, possibly behind a confirm prompt).
6. Update `journal/YYYY-MM-DD.md` and `trade-log.jsonl` with final state.
7. Scan open positions for the tiered trailing stop (12%/8%/6%/4% bands per `strategy.md` §0.3).

## Phase skills

The SOP is split into four phase-specific skills under `.claude/skills/`. Each defers to
`CLAUDE.md` and `references/strategy.md` — they are entry points, not replacements.

| Skill | Phase | Recommended cron (America/New_York) |
| --- | --- | --- |
| `pre-market` | Research & draft candidates (no orders) | `0 9 * * 1-5` (09:00 ET) |
| `market-open` | Execute planned trades + set stops | `35 9 * * 1-5` (09:35 ET) |
| `daily-summary` | EOD snapshot, final stop sweep, reflection | `55 15 * * 1-5` (15:55 ET) |
| `weekly-review` | Weekly P&L recap + tuning suggestions | `0 16 * * 5` (16:00 ET Fri) |

Invoke any of them by name (`/pre-market`, `/market-open`, …) or let them auto-activate from the
prompts in their descriptions.

## Automating with a Claude Code routine

Claude Code routines run your SOP on a schedule from Anthropic-managed cloud infrastructure, so
they keep working when your laptop is closed. See the [routines documentation](https://code.claude.com/docs/en/routines).

### One-time setup

1. Push this repo to a GitHub repository.
2. Connect that repository to Claude Code on the web (`/web-setup` from the CLI).
3. Add the **Robinhood Agentic Trading** MCP connector to your claude.ai account at
   [Settings → Connectors](https://claude.ai/customize/connectors). Routines can only use
   connectors connected to your claude.ai account — locally-installed MCPs are not visible.

### Create the routine

Recommended: one routine with the four triggers above. Each trigger invokes the matching phase
skill. A minimal single-trigger fallback is just `market-open` at 09:35.

**Prompt (paste into the routine):**

```text
Follow this repo's CLAUDE.md (the AI Trading Agent SOP dispatcher) and run today's phase.
Verify all hard preconditions and halt with a written reason if any fail — never trade on a
partial check. Honor config.toml (paper unless mode = "live"). If require_risk_review = true,
spawn the risk-reviewer subagent and proceed only on "approve". Write the trade-log.jsonl line
BEFORE any MCP order tool. Update journal/{today}.md with all sections, including the
End-of-Day Reflection. The non-negotiable rules in references/strategy.md §0 are absolute.
```

### Routine safety notes

- The routine runs **autonomously**, with no approval prompts during the run. The trade-log +
  Decision Framework + the risk-reviewer (mandatory in live) + the risk caps, cash reserve, and
  `block_tickers` are the only gates between the cloud session and a live Robinhood order.
- Keep `mode = "paper"` for the first ≥ 30 trading days. Read the journals and trade-log
  analytics before flipping live.
- A cloud routine can push to `claude/*`-prefixed branches by default; journal commits land
  there as PRs you review locally.

## Local automation alternatives

- **macOS LaunchAgent / cron** — run `claude -p "Run today's SOP phase"` from launchd or cron.
  Requires your laptop on and the CLI authenticated.

The hard requirement either way is that **the Robinhood MCP connector is reachable from wherever
the SOP runs**.

## Notifications

`scripts/notify.sh` posts a push notification to an [ntfy](https://ntfy.sh) topic. Set your
credentials in `.env` (copied from `.env.example`) and the phase skills will call it
automatically.

```bash
# .env
NTFY_TOKEN=tk_...                        # required
NTFY_SERVER=https://ntfy.example.com     # optional, default https://ntfy.sh
NTFY_TOPIC=agentic-trading               # optional, default agentic-trading
```

```bash
# Manual test
./scripts/notify.sh -t "market-open" "Bought 5 NVDA @ $847.50"
./scripts/notify.sh -t "stop hit" -p 5 -T "warning" "TSLA trailing stop fired"
```

Notification behavior per phase:
- **pre-market** — fires only when urgent (high-tier candidate, open position near stop, or stop condition active)
- **market-open** — fires only when a trade or exit is placed
- **daily-summary** — always fires once with the EOD recap
- **weekly-review** — always fires once with the weekly summary

## Analytics

`trade-log.jsonl` is the single source of truth for every trade across every day.

```bash
# Latest state per intent
jq -s 'group_by(.intent_id) | map(max_by(.timestamp_utc))' trade-log.jsonl

# Realized P&L by strategy
jq -s '[.[] | select(.side=="sell" and .result=="filled")] | group_by(.signal_source)
       | map({src: .[0].signal_source, pnl: ([.[].realized_pnl_usd] | add)})' trade-log.jsonl

# Realized P&L by theme
jq -s '[.[] | select(.side=="sell" and .result=="filled")] | group_by(.theme)
       | map({theme: .[0].theme, pnl: ([.[].realized_pnl_usd] | add)}) | sort_by(-.pnl)' trade-log.jsonl
```

```sql
-- DuckDB
CREATE VIEW trades AS SELECT * FROM read_json_auto('trade-log.jsonl');
SELECT theme, signal_source, SUM(realized_pnl_usd) AS pnl, COUNT(*) AS n
FROM trades WHERE side='sell' AND result='filled'
GROUP BY theme, signal_source
ORDER BY pnl DESC;
```

See `references/strategy.md` §7.1 for the full schema and recipes.

## Stopping the SOP

- **Return to paper (no real orders):** set `mode = "paper"` in `config.toml`.
- **Halt all new orders (exits keep running):** create an empty `KILL_SWITCH` file at repo root.
- **Routine paused/deleted:** toggle or delete it at [claude.ai/code/routines](https://claude.ai/code/routines).

## Reading the SOP

1. Read `CLAUDE.md` — the dispatcher (goal, rules, loop, decision framework).
2. Read `references/strategy.md` — the canonical strategies, sizing, exits, and the
   non-negotiables in §0.
3. Read `references/risk-review.md` — the two-agent rule-check.
4. Read `themes.toml` — the ticker → theme mapping for P&L analytics.

## Roadmap / Ideas

- **Re-introduce the cluster signals** (politician + insider Form 4) from `_archived/` as an
  additional candidate source alongside the technical strategies.
- **Time-state policy** (morning / midday / power-hour modifiers) — archived; re-add if the
  paper track record shows a time-of-day edge worth the complexity.
- **Backtest harness** — replay historical OHLCV against the strategy rules to validate changes
  before they touch real money.
- **Signal-quality metrics** — hit rate and forward return per strategy to decide what to keep.

---

## Disclaimer

This is documented decision logic, not financial advice. The hard cap in `strategy.md` §0.1 and
the cash reserve in `config.toml` are user-settable; pick conservative levels and start in paper
mode.
