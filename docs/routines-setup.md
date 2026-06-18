# Claude Routines — setup for the AI Trading Agent SOP

> **Roadmap reference.** Fully autonomous trading is a roadmap item (see the README). The SOP is
> currently run **manually** — the user picks the trades. These prompts are kept as a draft for
> the autonomous phase and assume an automated candidate source (the planned stock screener)
> rather than the manual loop. Revisit once the screener and defined exit rules are validated in
> paper mode. The paths below (`config.toml`, `data/trade-log.jsonl`,
> `data/positions.jsonl`) match the current layout.

Ready-to-paste instruction sets for running the SOP phase skills as scheduled
[Claude routines](https://code.claude.com/docs/en/routines). Create them at
[claude.ai/code/routines](https://claude.ai/code/routines) ("New routine" → **Remote**) or via
`/schedule` in the CLI, then add the cron schedule from each section.

## Read this first — cloud routines differ from local runs

Routines execute on Anthropic-managed cloud infrastructure, not your laptop. Three consequences
shape every prompt below:

1. **State must be committed back, or the chain breaks.** Each run clones this repo fresh from
   the default branch and works on a `claude/`-prefixed branch. The SOP is a chained workflow —
   `stock-trader` reads the journal `market-research` drafted, `portfolio-review` reads the journals +
   position state. None of that survives
   across runs unless each routine **commits and pushes its `journal/` changes back to the
   default branch.** (Note: `data/` is gitignored — local-only trade state does not survive a
   fresh cloud clone, which is a gap the autonomous phase must resolve before it can rely on it.)
   So:
   - Enable **Permissions → Allow unrestricted branch pushes** for this repo on every routine
     that writes (all four), so they can push to `main` instead of only `claude/*`. **This toggle
     is required** — without it the run physically cannot push to `main`, so it falls back to
     pushing a `claude/*` branch and opening a pull request (which leaves the state stranded off
     `main`, and the next phase reads stale data). Set it in the routine's **Edit → Permissions**
     tab; the CLI/`/schedule` cannot.
   - Every prompt ends with a commit + push step that pushes **directly to `main`** (`git push
     origin HEAD:main`) and explicitly says NOT to open a PR.
2. **The Robinhood MCP must be a claude.ai connector.** A server you added locally with
   `claude mcp add` does **not** transfer to the cloud. Add Robinhood as a connector at
   [claude.ai/customize/connectors](https://claude.ai/customize/connectors), or declare it in a
   committed `.mcp.json`. Under **Connectors** on each routine, keep Robinhood and remove
   everything the SOP doesn't use.
3. **Secrets live in the environment, not `.env`.** `.env` is gitignored, so it is absent from
   the clone. Set `NTFY_TOKEN` (and any Robinhood auth the connector needs) as **environment
   variables** on the routine's cloud environment. The skills already fall back to emitting the
   message as the final session line if `NTFY_TOKEN` is missing, but env vars let notifications
   actually fire.

**Network access:** the **Default** environment's *Trusted* policy covers package registries and
common dev domains. `market-research` needs web search for catalysts and `portfolio-review` may fetch SPY
data — if either is blocked, edit the environment → **Network access → Custom** and allow the
domains they hit (or **Full**). MCP connector traffic is already routed through Anthropic, so the
Robinhood connector works without allowlisting its host.

**Common settings for all three routines:**

| Field | Value |
| --- | --- |
| Repository | this repo (`ai-trading-agent-sop`) |
| Model | Per-routine (see each section) — **Opus for `stock-trader`** (the only phase that places real orders); **Sonnet** for `market-research` and `portfolio-review` |
| Connectors | Robinhood only (remove the rest) |
| Permissions | ☑ Allow unrestricted branch pushes (so it can push to the default branch) |
| Environment vars | `NTFY_TOKEN`, plus any Robinhood connector secrets |
| Schedule timezone | America/New_York |

Each prompt below is **self-contained** — routines run with no human in the loop, so the prompt
restates the entry point, the safety floor, and the commit step rather than assuming an
interactive operator.

---

## 1. Market research

- **Name:** `SOP — Market research`
- **Model:** Sonnet — research/scoring, no orders; its output is re-reviewed by the Opus
  `stock-trader` run. (Closest call of the non-trading two; bump to Opus if idea quality slips.)
- **Schedule (cron, America/New_York):** `0 9 * * 1-5` — 09:00 ET, before the 09:30 open
- **Trigger:** Schedule

**Prompt:**

```text
You are running the AI Trading Agent SOP, market research phase, fully autonomously in a
cloud session. There is no human to confirm anything.

1. Read and obey ./CLAUDE.md and ./references/strategy.md. The §0 non-negotiable rules override
   everything. This phase runs BEFORE the open — the market is closed, so you MUST NOT invoke any
   Robinhood order tool.
2. Execute the .claude/skills/market-research/SKILL.md instructions end to end: verify preconditions
   (config.toml parses, no KILL_SWITCH); resolve the SOP universe from the cache
   data/watchlist.json per strategy.md §2 (a fresh cloud clone has no data/, so the cache is
   missing → refresh once from the Robinhood connector; otherwise read the cache — the weekly
   portfolio-review handles the standing refresh);
   read the Robinhood balance + open positions; web-search today's catalysts
   (earnings, economic data with ET release times, sector momentum, geopolitics); surface
   anything notable on held or watchlist names; and write everything to journal/{YYYY-MM-DD}.md
   (Portfolio Status, Market Research, later sections as stubs).
3. Do NOT write to data/trade-log.jsonl and do NOT call any order tool.
4. Follow the skill's "silent unless urgent" notification policy.
5. FINALLY, persist state so the stock-trader phase can read it: stage journal/, commit with
   message "market-research {YYYY-MM-DD}: drafted N trade ideas", and push
   the commit DIRECTLY to the default branch (main) — `git push origin HEAD:main`. Do NOT open a
   pull request and do NOT push to a claude/* branch; this state must land on main so the
   stock-trader phase reads it. If nothing changed, say so and skip the commit.

Report back in <=5 lines: account snapshot, top catalysts, the 2-3 ideas, any urgent flag, and
the journal path.
```

---

## 2. Stock-trader execution

- **Name:** `SOP — Stock-trader execution`
- **Model:** **Opus** — the only phase that places real orders; highest stakes and reasoning load
  (precondition gating, risk-reviewer subagent, order pricing).
- **Schedule (cron, America/New_York):** `35 9 * * 1-5` — 09:35 ET, just after the open
- **Trigger:** Schedule

> ⚠️ This is the only phase that can place orders. It places **real orders only when
> `config.toml::mode = "live"`**; in `paper` mode it logs `result: "paper"` and calls no order
> tool. Confirm `mode` is what you intend before enabling this routine, and in live mode confirm
> `require_risk_review = true` (the SOP halts otherwise).
>
> Note: this routine runs the `stock-trader` skill against the **planned set** drafted by the
> market-research run. A cloud routine has no human to confirm, so the risk-reviewer's decision is
> final (it skips on reject rather than asking). Interactive single trades are run on-demand from
> the CLI.

**Prompt:**

```text
You are running the AI Trading Agent SOP, stock-trader execution phase, fully autonomously in a
cloud session. There is no human to confirm trades — execution is autonomous and the
risk-reviewer subagent is the pre-trade gate (skip on reject; do NOT ask).

1. Read and obey ./CLAUDE.md and ./references/strategy.md. The §0 non-negotiable rules override
   everything (limit orders preferred, market only when a limit can't fill the intent;
   extended hours allowed; journal every active day).
2. Verify ALL hard preconditions in CLAUDE.md in order — MCP/Robinhood connector reachable,
   account is the dedicated Agentic account, market session available, config.toml valid,
   no KILL_SWITCH, data/trade-log.jsonl writable. HALT with a written reason on any failure; do
   not trade on a partial check. (The watchlist resolves from the cache per strategy.md §2 — not
   a halt condition.)
3. Execute .claude/skills/stock-trader/SKILL.md end to end as a PLANNED SET: load the planned
   trades from today's journal/{YYYY-MM-DD}.md; per trade set the order type/price (§0.1), and if
   require_risk_review = true write proposals/{intent_id}.json, spawn the risk-reviewer subagent,
   wait for its decision, write reviews/{intent_id}.json, and skip on reject. Write the `pending`
   data/trade-log.jsonl line BEFORE any order tool. Execute by mode (paper = log only; live = place
   the order). Record each buy fill in data/positions.jsonl. Update the Trades Executed and
   Positions Closed tables, and write the End-of-Day Reflection, in today's journal.
4. Follow the skill's "message only if a trade is placed" notification policy.
5. FINALLY, persist state: stage data/trade-log.jsonl, data/positions.jsonl, proposals/, reviews/, and
   journal/, commit with message "stock-trader {YYYY-MM-DD}: placed N orders [mode]", and push the
   commit DIRECTLY to the default branch (main) — `git push origin HEAD:main`. Do NOT open a pull
   request and do NOT push to a claude/* branch. If nothing changed, say so and skip the commit.

Report back in <=5 lines: orders placed (count + mode), positions touched, stop conditions hit,
and the data/trade-log.jsonl + journal paths.
```

---

## 3. Portfolio review

- **Name:** `SOP — Portfolio review`
- **Model:** Sonnet — read-only analytics, lessons, and *suggested* tuning. No orders, no live
  decisions.
- **Schedule (cron, America/New_York):** `30 17 * * 5` — 17:30 ET each Friday, after the week's
  close. (Or run on-demand; this is a low-trade-frequency account.)
- **Trigger:** Schedule

**Prompt:**

```text
You are running the AI Trading Agent SOP, portfolio review phase, fully autonomously in a cloud
session. This phase is READ-ONLY over trade data — it never places orders and never edits
data/trade-log.jsonl or the daily journals.

1. Read ./CLAUDE.md and ./references/strategy.md for context.
2. Execute .claude/skills/portfolio-review/SKILL.md end to end: force-refresh the watchlist cache
   data/watchlist.json from the Robinhood connector (strategy.md §2); snapshot current holdings
   from data/positions.jsonl and refresh each one's unrealized P&L against a live quote; compute the
   account's total return (realized + unrealized) since inception and compare against SPY over the
   same window — the goal is to beat the S&P 500, and this is measurable even with zero closed
   trades; report realized P&L + win rate from data/trade-log.jsonl when trades have closed (say
   "none closed yet" otherwise); capture 3-5 lessons through the Peter Lynch lens applied to what
   is held now. Prepend a dated entry (## {YYYY-MM-DD}, newest-first) to the living ledger
   journal/portfolio-review.md with sections: Snapshot, Total Return vs SPY, Realized P&L, Lessons.
3. This phase sends NO notification — write the ledger and report back in-session only.
4. FINALLY, persist state: stage journal/portfolio-review.md, commit with message
   "portfolio-review {YYYY-MM-DD}", and push the commit DIRECTLY to the default branch (main) —
   `git push origin HEAD:main`. Do NOT open a pull request and do NOT push to a claude/* branch.

Report back as the one message (<=6 lines): review date, open positions + unrealized P&L, total
return vs SPY since inception, realized P&L + win rate (or "none closed yet"), and the
journal/portfolio-review.md path.
```

---

## Suggested order of operations

1. Add the **Robinhood MCP as a connector** on claude.ai and confirm it authenticates.
2. Set `NTFY_TOKEN` (and Robinhood secrets) as **env vars** on the routine environment.
3. Confirm `config.toml::mode` — start with `paper` to validate the full chain end to end before
   flipping `stock-trader` to `live`.
4. Create the three routines with the prompts + crons above; enable **unrestricted branch pushes**
   on each.
5. Use **Run now** on `market-research` first, open the run, and confirm it pushed a journal commit to
   the default branch — that proves the state-persistence chain works before the others depend on
   it.
```
