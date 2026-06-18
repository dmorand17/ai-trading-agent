# Risk Review (Two-Agent Pattern)

When `require_risk_review = true` in `config.toml`, the Trader (main session following
`CLAUDE.md`) **must** spawn the `risk-reviewer` subagent on every candidate trade and only invoke
the Robinhood MCP order tool after an `approve` decision.

The Reviewer's definition lives at `.claude/agents/risk-reviewer.md`. This file documents the
Trader-side workflow, the proposal/decision artifacts, and the failure modes.

## 1. Why split

A single agent that both picks and places the order tends to confirm its own thesis. A second
agent that didn't propose the trade catches two failure modes:

1. **Stale rule application.** The Trader was last told `mode` was `paper`; the user changed it
   in `config.toml` an hour ago. The Reviewer reads the file fresh.
2. **Bias under conviction.** Enthusiasm makes the Trader rationalize bending the rules. The
   Reviewer's prompt forces adversarial rule-checking.

The Reviewer **does not re-score the trade.** It only checks rules — keeping the runtime cost
low and the "Reviewer disagrees with the pick" failure mode impossible.

## 2. Flow

```
Trader (main session, CLAUDE.md)
   │ composes the pre-trade review block for the user-directed trade
   ├─► writes proposals/{intent_id}.json
   ├─► spawns risk-reviewer subagent with the proposal
   │     Reviewer reads: config.toml, strategy.md,
   │       data/trade-log.jsonl, KILL_SWITCH, journal/today.md
   │     Reviewer returns: {decision: approve|reject, reasons: [...]}
   ├─► writes reviews/{intent_id}.json
   ├─► if approve: append pending trade-log line → invoke MCP order tool → append final line
   └─► if reject:  append trade-log line with result "rejected_by_risk_review" +
                   rejection_reasons; journal "Skipped — Reviewer rejected: <reasons>"
```

## 3. Proposal artifact

The Trader writes one file per candidate to `proposals/{intent_id}.json` (canonical schema in
`.claude/agents/risk-reviewer.md`):

- `intent_id`, `ticker`, `side`, `order_type`, `qty`, `limit_price`, `dollar_amount`
- `account_snapshot` with `account_id_masked`, `total_equity_usd`, `cash_usd`
- `market_status`

`proposals/` is gitignored.

## 4. Review artifact

The Trader writes `reviews/{intent_id}.json` on the Reviewer's behalf:

```json
{
  "intent_id": "...",
  "decision": "approve",
  "reasons": [],
  "checks_passed": ["A.1", "..."],
  "checks_skipped": ["D.2 — account id not independently verifiable"],
  "reviewer_version": "2026-06-16",
  "reviewed_at_utc": "2026-06-16T14:03:35Z"
}
```

`reviews/` is gitignored. Reviews are immutable once written.

## 5. Trade-log integration

On reject, the Trader still writes one line to `data/trade-log.jsonl`:

```json
{
  "intent_id": "...",
  "timestamp_utc": "...",
  "mode": "live",
  "ticker": "ACME",
  "side": "buy",
  "order_type": "limit",
  "qty": 5,
  "limit_price": 42.25,
  "result": "rejected_by_risk_review",
  "rejection_reasons": [
    "§0.1 order type: limit_price 95.00 is >5% through the market (ask 42.25)"
  ],
  "rules_version": "2026-06-16"
}
```

## 6. When to require review

In `config.toml`:

```toml
require_risk_review = true   # default true
```

- **`true` (recommended):** every candidate goes through the Reviewer regardless of mode — so
  the daily journal reflects what would have been blocked in live.
- **`false`:** Trader skips the Reviewer. **Paper mode only** — use during the very first
  shakedown before the Reviewer scaffolding is validated. **Mandatory `true` in live mode:** the
  Reviewer is the pre-trade gate. Live mode halts and refuses to place orders if this is `false`.

## 7. Trader-side spawn prompt

```
You are the risk-reviewer subagent. Review the following trade proposal against
references/strategy.md §0, config.toml, and data/trade-log.jsonl. Return a single JSON
decision object per .claude/agents/risk-reviewer.md.

Proposal:
{INLINE_PROPOSAL_JSON or path to proposals/{intent_id}.json}

Read config.toml, references/strategy.md, data/trade-log.jsonl, and check for KILL_SWITCH.
Use the checklist in your system prompt. No prose, JSON only.
```

## 8. Failure modes & escalations

- **Reviewer times out / returns malformed JSON.** Treat as reject. Log `result:
  "rejected_by_risk_review"`, `rejection_reasons: ["reviewer_malformed_response"]`. Surface at
  end of loop.
- **Trader bypasses the Reviewer.** Should be impossible — the loop calls the Reviewer before
  any order tool. A `submitted` trade-log line with no matching `reviews/{intent_id}.json` is a
  critical audit failure; investigate immediately.
