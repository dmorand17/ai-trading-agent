# AI Trading Agent — Daily Runbook

The SOP runs as a sequence of Claude Code slash-command invocations. Each phase is a skill that
reads `CLAUDE.md` and `references/strategy.md` and follows those rules exactly. Nothing here
overrides `strategy.md §0`.

This is the **manual phase**: the user picks the trades; the skills handle research, execution
through the audit gates, and review.

---

## Typical day (Mon–Fri, US market days)

| When | Phase | Slash command |
|---|---|---|
| Before the open / any market brief | Research & context | `/market-research` |
| Any time the market is open/extended | Trade execution (single or planned set) | `/stock-trader` |
| Weekly (Fri) / on-demand | Book health & lessons | `/portfolio-review` |

The most common entry point is `/stock-trader` for a single trade. The other phases are optional
structure around it.

---

## Stock trader (`/stock-trader`) — the primary entry point

**When:** Any time the market session is available (regular or extended). Human-in-the-loop.

**What it does:** Executes trades through the audit gates (risk-reviewer, `data/trade-log.jsonl`,
journal) — a single user-specified trade, or a planned set drafted in today's journal.
- You choose the ticker, side (buy/sell), order type (limit/market), size, and price.
- Off-watchlist tickers are allowed — a bought ticker is added to the Agent WatchList.
- If the risk-reviewer rejects, it asks whether to override rather than silently skipping.
- After the day's trades, it writes the End-of-Day Reflection to the journal.

**Required:** ticker + side. Optional: order type (defaults to limit), size, price — if missing,
the skill pulls live data and shows bid/ask + a suggested limit (~2% from price) before asking.

**Halts if:** Market fully closed (just tells you and stops).

### Sample prompts

```
/stock-trader NVDA buy
Buy 10 shares of RKLB at a limit.
Sell half my AMD position.
I want to buy LUNR — show me the current price and suggest a limit.
Execute today's planned trades.
```

---

## Market research (`/market-research`)

**When:** Before the open, or any time you want a market brief. No orders are placed.

**What it does:** Reads account balance + open positions, web-searches today's catalysts
(earnings, economic data, sector momentum, geopolitics), surfaces anything notable on held or
watchlist names, and writes it to `journal/YYYY-MM-DD.md`. Gives you the context to decide what
to trade.

**Notification:** Silent unless a catalyst materially affects a held position.

---

## Portfolio review (`/portfolio-review`)

**When:** Weekly (Friday after the close) or on-demand ("how's the book?"). Read-only — never places orders or edits
prior logs.

**What it does:** Snapshots current holdings + unrealized P&L, computes account total return vs
SPY since inception (the benchmark goal — measurable from day one), reports realized P&L + win
rate when trades have closed, captures 3–5 lessons through the Peter Lynch lens, and prepends a
dated entry to the living ledger `journal/portfolio-review.md`.

**Notification:** None — writes the ledger and reports back in-session only.

---

## Key files

| File | Written by | Notes |
|---|---|---|
| `journal/YYYY-MM-DD.md` | market-research → stock-trader | One per trading day |
| `journal/portfolio-review.md` | portfolio-review | Single living ledger, newest entry first |
| `data/trade-log.jsonl` | stock-trader | Append-only; the single analytics source. Gitignored. |
| `data/positions.jsonl` | stock-trader, portfolio-review | Open-position state (total qty + P&L). Gitignored. |
| `config.toml` | You (edit manually) | `mode`, `require_risk_review`, `sop_universe_list_name` |
| `KILL_SWITCH` | You (create/delete manually) | Presence halts all new orders; delete to re-enable |

---

## Stop conditions

Any of these halts the current phase and reports to you:

- Market is fully closed and an order was requested (research/journal still run)
- MCP unreachable mid-loop
- KILL_SWITCH file present at repo root
- `config.toml` missing or unparseable
- Agent WatchList not found on Robinhood
- `data/trade-log.jsonl` unwritable
