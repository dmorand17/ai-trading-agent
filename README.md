# AI Trading Agent SOP

A Claude Code Standard Operating Procedure for US-equity trading via the [Robinhood Agentic
Trading MCP](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).

**The goal: beat the S&P 500 (SPY) — for fun.** This is a small, for-fun account (under $1k). The
SOP is a **set of markdown files** — there is no application code. The Claude Code session is the
executor at runtime; `CLAUDE.md` is the always-loaded dispatcher.

This is the **manual / human-in-the-loop phase**: the user picks what to trade and the agent
executes it through the audit-trail gates (risk-reviewer + trade log). A programmatic stock
screener and fully autonomous trading are on the [roadmap](#roadmap).

## Trading philosophy — Peter Lynch, "let your winners run"

The guiding style is Peter Lynch's:

- **Let your winners run.** The biggest gains come from holding the rare multi-bagger through the
  noise — don't trim a position just because it's up.
- **Don't pull the flowers and water the weeds.** Lynch's warning: don't sell your winning stocks
  prematurely to buy more of your losing stocks. *It only takes a handful of massive winners to
  make a lifetime of investing successful.*

## File layout

```
.
├── CLAUDE.md                         ← Always-loaded dispatcher: goal, rules, manual loop
├── README.md                         ← (this file)
├── RUNBOOK.md                        ← Day-to-day operating guide for the phase skills
├── KILL_SWITCH                       ← (create to halt new orders; delete to resume)
├── config/
│   └── config.toml                   ← User-edited: mode, universe pointer, risk-review toggle
├── data/                             ← Local-only, gitignored (never committed)
│   ├── trade-log.jsonl               ← Append-only audit log (single analytics source)
│   ├── positions.jsonl               ← Open-position state (total qty + current P&L)
│   └── watchlist.json                ← Cached Robinhood universe (refresh: strategy.md §2)
├── docs/
│   └── routines-setup.md             ← (roadmap) cloud-routine prompts for autonomous runs
├── journal/
│   ├── YYYY-MM-DD.md                 ← Daily journal (one per trading day)
│   └── portfolio-review.md           ← Living book-health ledger (newest-first)
├── scripts/
│   └── notify.sh                     ← ntfy push notifications
├── references/
│   ├── strategy.md                   ← Order rules, mode, kill switch, log schemas (canonical)
│   ├── risk-review.md                ← Two-agent risk-review flow
│   └── robinhood-mcp.md              ← Robinhood MCP tool reference
└── .claude/
    ├── agents/
    │   └── risk-reviewer.md          ← Adversarial rule-check subagent
    └── skills/                       ← Phase entry points (stock-trader, market-research, …)
```

> The original cluster-signal engine (congressional buys, insider Form 4), the time-state policy,
> and the technical-strategy scoring engine live in `_archived/` for reference. They are not part
> of the active SOP.

## Configuration

### `config/config.toml`

```toml
mode = "paper"                              # "paper" | "live"
sop_universe_list_name = "Agent WatchList"  # Robinhood watchlist; cached to data/watchlist.json (§2)
require_risk_review = true                  # risk-reviewer gates every order; MANDATORY in live
```

Full schema in `references/strategy.md` §1.1.

### `.env` (gitignored)

Robinhood MCP auth is handled by the connector itself. Only third-party keys (e.g. the ntfy
push-notification token) go here. See `.env.example`.

## Prerequisites

1. **Robinhood Agentic account** (separate from your primary individual account). Onboard via
   desktop. See the [Robinhood Agentic Trading overview](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).
2. **Robinhood MCP connector installed** in Claude Code:
   - Endpoint: `https://agent.robinhood.com/mcp/trading`
   - Transport: HTTP — install via Claude Code's connectors UI or `~/.claude/.mcp.json`.
3. **`config/config.toml`** present and valid (create from the schema above).
4. **Agent WatchList** created on Robinhood (display name must match `sop_universe_list_name`).

## Running the SOP interactively

From a Claude Code session **with this repo as the working directory**:

```
> Buy 5 NVDA at a limit
> Sell half my AMD position
> Run market research
> Review the trade log
```

`CLAUDE.md` (the dispatcher) is always loaded, so the agent knows the goal, the safety rules, and
the manual loop. The `stock-trader` skill is the primary entry point for trade execution; the
phase skills (below) cover research, execution, and review.

## Phase skills

| Skill | Phase |
| --- | --- |
| `stock-trader` | Trade execution — single user-directed trade or a planned set, through the audit gates (the primary entry point) |
| `market-research` | Research & context — balance, catalysts, watchlist notes (no orders) |
| `portfolio-review` | Book snapshot + total return vs SPY + lessons (on-demand/monthly) |

Invoke any by name (`/stock-trader`, `/market-research`, …) or let them auto-activate from the prompts
in their descriptions. See `RUNBOOK.md` for the day-to-day flow.

## Notifications

`scripts/notify.sh` posts a push notification to an [ntfy](https://ntfy.sh) topic. Set your
credentials in `.env` (copied from `.env.example`).

```bash
# .env
NTFY_TOKEN=tk_...                        # required
NTFY_SERVER=https://ntfy.example.com     # optional, default https://ntfy.sh
NTFY_TOPIC=agentic-trading               # optional, default agentic-trading
```

```bash
./scripts/notify.sh -t "stock-trader" "Bought 5 NVDA @ $847.50"
```

## Analytics

`data/trade-log.jsonl` is the single source of truth for every trade. It's gitignored — kept
local only.

```bash
# Latest state per intent
jq -s 'group_by(.intent_id) | map(max_by(.timestamp_utc))' data/trade-log.jsonl

# Total realized P&L on closed sells
jq -s '[.[] | select(.side=="sell" and .result=="filled")] | map(.realized_pnl_usd) | add' data/trade-log.jsonl
```

See `references/strategy.md` §5.1 for the full schema.

## Stopping the SOP

- **Return to paper (no real orders):** set `mode = "paper"` in `config/config.toml`.
- **Halt all new orders:** create an empty `KILL_SWITCH` file at repo root.

## Roadmap

The current phase is deliberately minimal — manual trades, light rules. Planned additions, in
rough priority order:

- **Stock screener** — a programmatic candidate source (technical and/or fundamental screens) to
  surface trade ideas instead of picking them by hand. This replaces the archived scoring engine.
- **Defined exit rules** — a trailing stop, time stop, or rebalancing logic to systematize exits.
  Deferred for now (exits are user-directed), but the core risk-management piece to add next.
- **Fully agentic / automated trading** — run the SOP unattended on a schedule (Claude routines or
  local cron). Draft cloud-routine prompts are kept in `docs/routines-setup.md`; revisit
  once the screener and exit rules are validated in paper mode.
- **Backtest harness** — replay historical data against the screener + exit rules to validate
  changes before they touch real money.
- **Re-introduce the cluster signals** (politician + insider Form 4) from `_archived/` as an
  additional candidate source.

## Reading the SOP

1. `CLAUDE.md` — the dispatcher (goal, rules, manual loop).
2. `references/strategy.md` — the canonical order rules, log schemas, and the non-negotiables in
   §0.
3. `references/risk-review.md` — the two-agent rule-check.

---

## Disclaimer

This is documented decision logic, not financial advice. Start in paper mode; this is a for-fun
project with a small account.
