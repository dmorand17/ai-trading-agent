---
name: market-open
description: Market-open execution phase of the AI Trading Agent SOP. Run the full SOP loop — verify preconditions, execute the planned/drafted trades through the risk-reviewer and trade-log gates, and set the profit-protection trailing stops. Use for "/market-open", "execute today's trades", "open the session", or a scheduled post-open trigger. Messages only if a trade is placed.
---

# Market-open — Phase 2: Execute planned trades

Recommended cron (America/New_York): `35 9 * * 1-5` (09:35 ET, just after the open).

This is the **execution phase** of the AI Trading Agent SOP. Read the project `CLAUDE.md` and
`references/strategy.md` and follow them exactly — this skill is a phase-specific entry point.
`strategy.md` §0 is non-negotiable and overrides everything here.

## Do this

1. **All hard preconditions** (`CLAUDE.md`) — MCP connected, account is the **Agentic** account,
   market **open**, `mode.toml`/`watchlist.json` valid, no `KILL_SWITCH`, `trade-log.jsonl`
   writable. Halt with a written reason on any failure; do not trade on a partial check.
2. **Load drafted candidates** from today's journal Market Research / Draft Trade Ideas block
   (written by the `pre-market` phase). If the journal has no drafts (pre-market didn't run),
   score the watchlist now per `CLAUDE.md` loop steps 1–2 (`strategy.md` §A).
3. **Per candidate**, run the full SOP loop (`CLAUDE.md` loop steps 3–7):
   - Compute the conviction tier (`strategy.md` §3.1, §5 confluence) and size the position.
   - Run the 5-question Decision Framework (`CLAUDE.md`) if not already satisfied in the
     journal; re-check cash/positions live and confirm the firing strategy's read still holds.
   - If `require_risk_review = true`: write `proposals/{intent_id}.json`, spawn the
     `risk-reviewer` subagent, wait for its decision, write `reviews/{intent_id}.json`. On
     `reject` → log `rejected_by_risk_review` and skip.
   - **Write the `pending` `trade-log.jsonl` line BEFORE any MCP order tool** (§7, §6).
   - Execute by mode: paper → log `result: "paper"`, no MCP call. live → place the limit order
     (day, equity, buy), honoring `live_allowlist`, `block_tickers`, `require_manual_confirm`.
4. **Set/confirm trailing stops** on every resulting position (`strategy.md` §0.3, §4.3) —
   record `peak_mark` in `positions.jsonl`.
5. **Sweep open positions** for the §0.3 tiered trailing stop on the same pass.
6. **Update** `journal/{YYYY-MM-DD}.md` — fill the Trades Executed and Positions Closed tables.

## Notification policy: only if a trade is placed

Message only when an order is placed (paper or live) or an exit fires. Include ticker(s), side,
qty, limit, mode. No trade → stay silent.

<!-- TODO(notify): wire to scripts/notify.sh when ready, e.g.
       ./scripts/notify.sh -t "market-open" "<message>"
     Until then, emit the message as the final session line only when a trade or exit occurred;
     otherwise end silent. -->

## Report back (≤5 lines)

Orders placed (count + mode) · positions touched incl. any trailing-stop exits · stop conditions
hit · paths to `trade-log.jsonl` and today's journal.
