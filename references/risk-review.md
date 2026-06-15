# Risk Review (Two-Agent Pattern)

When `require_risk_review = true` in `config.toml`, the Trader (main session following `CLAUDE.md`)
**must** spawn the `risk-reviewer` subagent on every candidate trade and only invoke the
Robinhood MCP order tool after an `approve` decision.

The Reviewer's definition lives at `.claude/agents/risk-reviewer.md`. This file documents the
Trader-side workflow, the proposal/decision artifacts, and the failure modes.

## 1. Why split

A single agent that both scores a strategy and places the order tends to confirm its own thesis.
Two failure modes get caught by a second agent that didn't propose the trade:

1. **Stale rule application.** The Trader was last told `cash_reserve_pct` was 0.20; the user
   changed it in `config.toml` an hour ago. The Reviewer reads the file fresh.
2. **Bias under conviction.** A high score makes the Trader rationalize bending the 5-question
   framework. The Reviewer's prompt forces adversarial rule-checking.

The Reviewer **does not re-score the strategy.** It only checks rules — keeping the runtime cost
low and the "Reviewer disagrees with conviction" failure mode impossible.

## 2. Flow

```
Trader (main session, CLAUDE.md)
   │ scores the strategy set, applies the Decision Framework
   ├─► writes proposals/{intent_id}.json
   ├─► spawns risk-reviewer subagent with the proposal
   │     Reviewer reads: config.toml, strategy.md,
   │       trade-log.jsonl, KILL_SWITCH, journal/today.md
   │       (universe snapshot lives in the proposal — MCP-fetched by the Trader)
   │     Reviewer returns: {decision: approve|reject, reasons: [...]}
   ├─► writes reviews/{intent_id}.json
   ├─► if approve: append pending trade-log line → invoke MCP order tool → append final line
   └─► if reject:  append trade-log line with result "rejected_by_risk_review" +
                   rejection_reasons; journal "Skipped — Reviewer rejected: <reasons>"
```

## 3. Proposal artifact

The Trader writes one file per candidate to `proposals/{intent_id}.json` (canonical schema in
`.claude/agents/risk-reviewer.md`):

- `intent_id`, `ticker`, `side`, `qty`, `limit_price`
- `signal_source` (firing strategy or `+`-joined combo), `conviction_tier`, `conviction_score`
- `decision_framework` with Q1–Q5 answers
- `account_snapshot` with `account_id_masked`, `total_equity_usd`, `cash_usd`, `deployed_pct`
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
  "checks_skipped": ["D.4 — liquidity not verifiable from proposal"],
  "reviewer_version": "2026-06-15",
  "reviewed_at_utc": "2026-06-15T14:03:35Z"
}
```

`reviews/` is gitignored. Reviews are immutable once written.

## 5. Trade-log integration

On reject, the Trader still writes one line to `trade-log.jsonl`:

```json
{
  "intent_id": "...",
  "timestamp_utc": "...",
  "mode": "live",
  "signal_source": "trend+breakout",
  "ticker": "ACME",
  "side": "buy",
  "qty": 120,
  "limit_price": 42.25,
  "conviction_tier": "high",
  "conviction_score": 78,
  "result": "rejected_by_risk_review",
  "rejection_reasons": [
    "B.1 position cap: post-trade exposure 16.3% exceeds 15% per-position cap"
  ],
  "rules_version": "2026-06-15"
}
```

## 6. When to require review

In `config.toml`:

```toml
require_risk_review = true   # default true once the feature is enabled
```

- **`true` (recommended):** every candidate goes through the Reviewer regardless of mode — so
  the daily journal reflects what would have been blocked in live.
- **`false`:** Trader skips the Reviewer. **Paper mode only** — use during the very first
  shakedown before the Reviewer scaffolding is validated. **Mandatory `true` in live mode:** the
  SOP is fully autonomous (no human-in-the-loop confirmation), so the Reviewer is the sole
  pre-trade gate. Live mode halts and refuses to place orders if this is `false`.

## 7. Trader-side spawn prompt

```
You are the risk-reviewer subagent. Review the following trade proposal against
references/strategy.md §0, config.toml, and trade-log.jsonl. Return a single JSON decision
object per .claude/agents/risk-reviewer.md.

Proposal:
{INLINE_PROPOSAL_JSON or path to proposals/{intent_id}.json}

Read config.toml, references/strategy.md, trade-log.jsonl, and check for KILL_SWITCH. The
universe snapshot (the Robinhood watchlist symbols at proposal time) is included in the
proposal as `universe_snapshot`. Use the checklist in your system prompt. No prose, JSON only.
```

## 8. Failure modes & escalations

- **Reviewer times out / returns malformed JSON.** Treat as reject. Log `result:
  "rejected_by_risk_review"`, `rejection_reasons: ["reviewer_malformed_response"]`. Surface at
  end of loop.
- **Reviewer rejects 100% of candidates over N consecutive runs.** Likely rules drift (e.g.
  cash reserve too high vs current equity). Surface in the End-of-Day Reflection with a tuning
  suggestion.
- **Trader bypasses the Reviewer.** Should be impossible — the loop calls the Reviewer before
  any order tool. A `submitted` trade-log line with no matching `reviews/{intent_id}.json` is a
  critical audit failure; investigate immediately.

## 9. Validation

Before flipping `require_risk_review = true` in live mode, run ≥ 30 paper-trading days with the
Reviewer active. Confirm: it approves trades the Trader would have placed correctly; it rejects
for cited rule reasons, not vibes; `proposals/` and `reviews/` pair 1:1; no `submitted` line
lacks a matching `approve` review.
