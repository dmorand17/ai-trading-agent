# AI Trading Agent SOP — project instructions

This file is the always-loaded dispatcher for the AI Trading Agent SOP. It defines the goal,
the safety rules, the manual trading loop, and where to load detail on demand. The Claude Code
session is the executor at runtime — there is no application code.

## Goal

**Beat the S&P 500 (SPY), for fun.** This is a small, for-fun account (under $1k). The objective
is to outperform SPY total return over the long run — judged against the benchmark, not zero.
Capital is small and this is run manually for now; the rules are deliberately light.

The guiding style is **Peter Lynch — "let your winners run."** Don't pull the flowers to water
the weeds: don't sell winners to add to losers. A handful of big winners carries the account.

## When this SOP is in play

Engage the SOP when the user asks to: run the SOP / review the trade log / place a trade; or on
a manual cadence. The phase skills in `.claude/skills/` (`market-research`, `stock-trader`,
`portfolio-review`) are phase-specific entry points that all defer to this file and
`references/strategy.md`. The `stock-trader` skill is the human-in-the-loop entry point for trade
execution — a single user-directed trade ("buy 10 NVDA now") or a planned set; the user picks
ticker/side/order type and may override a risk-review reject.

## Non-negotiable rules (apply always, override everything)

Full mechanics in `references/strategy.md` §0.

1. **Prefer limit orders.** Recommend a limit ~2% from the current price (buys: `ask × 1.02`;
   sells: `bid × 0.98`). Use a market order only when a limit can't fill the intent (e.g. a
   fractional-share dollar buy) or when the user explicitly asks for one.
2. **Extended-hours trading is allowed.** Confirm the session state and pass the matching
   `market_hours` value. Only block when the market is fully closed (no session at all).
3. **Write a journal entry for any day the SOP does something.** No-trade scans record what was
   looked at and why nothing was taken.

## Hard preconditions (verify in order, halt on failure)

1. **MCP connected.** Run `tools/list`; confirm Robinhood trading tools are present. If not,
   tell the user the MCP is unreachable and stop.
2. **Account is the dedicated Agentic account** — not the user's primary individual account.
   Robinhood only permits agentic trading from dedicated Agentic accounts.
3. **Market session available.** If fully closed, scans continue but no order tool may fire.
4. **`config.toml` exists and parses.** Required: `mode`, `require_risk_review`. If
   missing, create with paper defaults and tell the user. **In live mode, `require_risk_review`
   must be `true`** — the risk-reviewer is the pre-trade gate. If `mode = "live"` and
   `require_risk_review = false`, halt and tell the user.
5. **SOP universe resolves (cache-first, never a halt).** Resolve the watchlist from
   `data/watchlist.json` per the `strategy.md` §2 refresh policy: read the cache by default;
   refresh from the MCP only on user request, when the cache is missing, or on the weekly
   `portfolio-review`; on a failed refresh, fall back to the cache and continue. The watchlist is a tracked/research list,
   not a trade gate — never halt on it.
6. **No kill switch.** If `KILL_SWITCH` exists at repo root, refuse to place orders (scans still
   allowed).
7. **`data/trade-log.jsonl` is writable.** No order tool may be invoked unless it is.

## Manual trading loop

```
1. Resolve the SOP universe from the local cache `data/watchlist.json` (a tracked/research list,
   not a trade gate; refresh policy in strategy.md §2). Refresh quotes for the names of interest.
2. The user decides what to buy or sell (a programmatic screener is a roadmap item). Apply the
   Peter Lynch philosophy: let winners run, don't sell strength to fund losers.
3. Emit a pre-trade review block per trade (ticker | side | type | qty | limit | account).
4. If require_risk_review = true: write proposals/{intent_id}.json + spawn the risk-reviewer
   subagent (references/risk-review.md). Proceed on "approve"; on "reject" in the autonomous
   loop, log and skip — in stock-trader, surface it and let the user decide.
5. Execute by mode: paper → log result "paper", no MCP call. live → place the order, then
   immediately log the result to data/trade-log.jsonl (strategy.md §4, §5).
7. On a buy fill, record/refresh the position in data/positions.jsonl (total qty + current P&L).
8. Update journal/{YYYY-MM-DD}.md.
```

## Load on demand

| When you need… | Load |
| --- | --- |
| Order rules, mode, kill switch, log + position schemas | `references/strategy.md` |
| When/how to spawn the risk-reviewer subagent | `references/risk-review.md` |
| Robinhood MCP tool reference (signatures, defaults, gotchas) | `references/robinhood-mcp.md` |

Do not preload references unless the loop needs them.

## Two logs + position state, all local

- **`data/trade-log.jsonl`** (gitignored, append-only, machine-readable) — one line per order
  state transition, written immediately after the MCP order tool returns. The analytics source.
  Schema in `strategy.md` §5.1.
- **`data/positions.jsonl`** (gitignored, append-only) — total quantity + current P&L per open
  position. Schema in `strategy.md` §5.3.
- **`journal/{YYYY-MM-DD}.md`** (human-readable, one per day) — Portfolio Status → Market
  Research → Trades Executed → Positions Closed → End-of-Day Reflection. Template in
  `strategy.md` §5.2.

## Safety defaults (overridden only by explicit user instruction)

- Default mode: **paper**.
- Default asset class: **US-listed common equity**. No options, crypto, OTC.
- Default order type: **limit**. No leverage, no shorting.

## Stop conditions

Halt and tell the user when: the market is fully closed and an order was requested; the MCP goes
unreachable mid-loop; `KILL_SWITCH` appears; or `config.toml` becomes unparseable. (A
failed watchlist refresh is **not** a halt — fall back to the `data/watchlist.json` cache, §2.)

## Reporting back

After each loop, summarize in ≤5 lines: trades placed (count + mode) · positions touched · stop
conditions hit · paths to `data/trade-log.jsonl` and today's `journal/{YYYY-MM-DD}.md`.

## UUID generation

Use `scripts/uuid.sh` to generate UUIDs (intent IDs, ref IDs). Do not use `python3 -c "import uuid; ..."` or other ad-hoc methods.

```bash
bash scripts/uuid.sh
```

## Notifications

Push notifications go via `scripts/notify.sh`. `NTFY_TOKEN`.  If `NTFY_TOKEN` is missing source the .env file

If `.env` is missing or the token is still unset after sourcing, emit the notification as the
final session line instead of failing silently.
