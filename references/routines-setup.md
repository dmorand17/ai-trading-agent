# Claude Routines — setup for the AI Trading Agent SOP

Ready-to-paste instruction sets for running the four SOP phase skills as scheduled
[Claude routines](https://code.claude.com/docs/en/routines). Create them at
[claude.ai/code/routines](https://claude.ai/code/routines) ("New routine" → **Remote**) or via
`/schedule` in the CLI, then add the cron schedule from each section.

## Read this first — cloud routines differ from local runs

Routines execute on Anthropic-managed cloud infrastructure, not your laptop. Three consequences
shape every prompt below:

1. **State must be committed back, or the chain breaks.** Each run clones this repo fresh from
   the default branch and works on a `claude/`-prefixed branch. The SOP is a chained workflow —
   `market-open` reads the journal `pre-market` drafted, `daily-summary` reads the day's
   `trade-log.jsonl`, `weekly-review` reads the week's journals. None of that survives across
   runs unless each routine **commits and pushes its `journal/` + `trade-log.jsonl` (+
   `positions.jsonl`, `themes.toml`) changes back to the default branch.** So:
   - Enable **Permissions → Allow unrestricted branch pushes** for this repo on every routine
     that writes (all four), so they can push to `main` instead of only `claude/*`.
   - Every prompt ends with a commit + push step.
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
common dev domains. `pre-market` needs web search for catalysts and `weekly-review` may fetch SPY
data — if either is blocked, edit the environment → **Network access → Custom** and allow the
domains they hit (or **Full**). MCP connector traffic is already routed through Anthropic, so the
Robinhood connector works without allowlisting its host.

**Common settings for all four routines:**

| Field | Value |
| --- | --- |
| Repository | this repo (`ai-trading-agent-sop`) |
| Model | Per-routine (see each section) — **Opus for `market-open`** (the only phase that places real orders); **Sonnet** for `pre-market`, `daily-summary`, and `weekly-review` |
| Connectors | Robinhood only (remove the rest) |
| Permissions | ☑ Allow unrestricted branch pushes (so it can push to the default branch) |
| Environment vars | `NTFY_TOKEN`, plus any Robinhood connector secrets |
| Schedule timezone | America/New_York |

Each prompt below is **self-contained** — routines run with no human in the loop, so the prompt
restates the entry point, the safety floor, and the commit step rather than assuming an
interactive operator.

---

## 1. Pre-market research

- **Name:** `SOP — Pre-market research`
- **Model:** Sonnet — research/scoring, no orders; its output is re-reviewed by the Opus
  `market-open` run. (Closest call of the non-trading three; bump to Opus if idea quality slips.)
- **Schedule (cron, America/New_York):** `0 9 * * 1-5` — 09:00 ET, before the 09:30 open
- **Trigger:** Schedule

**Prompt:**

```text
You are running the AI Trading Agent SOP, pre-market research phase, fully autonomously in a
cloud session. There is no human to confirm anything.

1. Read and obey ./CLAUDE.md and ./references/strategy.md. The §0 non-negotiable rules override
   everything. This phase runs BEFORE the open — the market is closed, so you MUST NOT invoke any
   Robinhood order tool.
2. Execute the .claude/skills/pre-market/SKILL.md instructions end to end: verify preconditions
   (config.toml parses, SOP universe list is fetchable from the Robinhood connector, no
   KILL_SWITCH); read the Robinhood balance + open positions; web-search today's catalysts
   (earnings, economic data with ET release times, sector momentum, geopolitics); score the
   watchlist against the strategy set; distill 2-3 actionable trade ideas through the 5-question
   Decision Framework; and write everything to journal/{YYYY-MM-DD}.md (Portfolio Status, Market
   Research, Draft Trade Ideas marked "DRAFT — not executed", later sections as stubs).
3. Do NOT write to trade-log.jsonl and do NOT call any order tool.
4. Follow the skill's "silent unless urgent" notification policy.
5. FINALLY, persist state so the market-open phase can read it: stage journal/ (and any updated
   themes.toml), commit with message "pre-market {YYYY-MM-DD}: drafted N trade ideas", and push
   to the default branch. If nothing changed, say so and skip the commit.

Report back in <=5 lines: account snapshot, top catalysts, the 2-3 ideas, any urgent flag, and
the journal path.
```

---

## 2. Market-open execution

- **Name:** `SOP — Market-open execution`
- **Model:** **Opus** — the only phase that places real orders; highest stakes and reasoning load
  (precondition gating, risk-reviewer subagent, tier sizing, trailing-stop math).
- **Schedule (cron, America/New_York):** `35 9 * * 1-5` — 09:35 ET, just after the open
- **Trigger:** Schedule

> ⚠️ This is the only phase that can place orders. It places **real orders only when
> `config.toml::mode = "live"`**; in `paper` mode it logs `result: "paper"` and calls no order
> tool. Confirm `mode` is what you intend before enabling this routine, and in live mode confirm
> `require_risk_review = true` (the SOP halts otherwise).

**Prompt:**

```text
You are running the AI Trading Agent SOP, market-open execution phase, fully autonomously in a
cloud session. There is no human to confirm trades — execution is autonomous and the
risk-reviewer subagent is the pre-trade gate.

1. Read and obey ./CLAUDE.md and ./references/strategy.md. The §0 non-negotiable rules override
   everything (15% position cap; limit orders preferred, market only for fractional entries;
   tiered trailing stop from day 1; journal every day; never trade when the market is closed).
2. Verify ALL hard preconditions in CLAUDE.md in order — MCP/Robinhood connector reachable,
   account is the dedicated Agentic account, market OPEN, config.toml valid, SOP universe list
   fetchable, no KILL_SWITCH, trade-log.jsonl writable. HALT with a written reason on any failure;
   do not trade on a partial check.
3. Execute .claude/skills/market-open/SKILL.md end to end: load the drafted candidates from
   today's journal/{YYYY-MM-DD}.md (if pre-market didn't run, score the watchlist now); per
   candidate run the full SOP loop — size by tier, run the 5-question Decision Framework, and if
   require_risk_review = true write proposals/{intent_id}.json, spawn the risk-reviewer subagent,
   wait for its decision, write reviews/{intent_id}.json, and skip on reject. Write the `pending`
   trade-log.jsonl line BEFORE any order tool. Execute by mode (paper = log only; live = place
   the limit order honoring block_tickers). Then set/confirm trailing stops on every resulting
   position and sweep all open positions for the §0.3 tiered trailing stop. Update the Trades
   Executed and Positions Closed tables in today's journal.
4. Follow the skill's "message only if a trade is placed" notification policy.
5. FINALLY, persist state: stage trade-log.jsonl, positions.jsonl, proposals/, reviews/, and
   journal/, commit with message "market-open {YYYY-MM-DD}: placed N orders [mode]", and push to
   the default branch. If nothing changed, say so and skip the commit.

Report back in <=5 lines: orders placed (count + mode), positions touched incl. trailing-stop
exits, stop conditions hit, and the trade-log.jsonl + journal paths.
```

---

## 3. Daily summary

- **Name:** `SOP — Daily summary`
- **Model:** Sonnet — mostly mechanical (snapshot, rules-based trailing-stop sweep, recap). Note:
  if the market is still open at 15:55 the sweep can place protective exits, but that's pure rule
  application, not discretion. Put on Opus if you want Opus on anything that can hit an order tool.
- **Schedule (cron, America/New_York):** `55 15 * * 1-5` — 15:55 ET, just before the close
- **Trigger:** Schedule

**Prompt:**

```text
You are running the AI Trading Agent SOP, end-of-day summary phase, fully autonomously in a cloud
session.

1. Read and obey ./CLAUDE.md and ./references/strategy.md. The §0 non-negotiable rules override
   everything.
2. Execute .claude/skills/daily-summary/SKILL.md end to end: check market status (if still open,
   protective exits/tightening may be placed; if closed, queue exits for the next open); run the
   final trailing-stop sweep across the whole book (update each peak_mark, recompute the tier
   band, close anything where current_mark <= peak_mark x (1 - band)); refresh the Portfolio
   Status snapshot in journal/{YYYY-MM-DD}.md with EOD cash, positions, equity, mode, market
   status; write the End-of-Day Reflection (required even on no-trade days); and recap the day
   from today's trade-log.jsonl lines (group by intent_id, take latest). Ensure the Trades
   Executed / Positions Closed tables are complete ("None today." if empty).
3. Follow the skill's notification policy: ALWAYS send exactly one summary message.
4. FINALLY, persist state: stage journal/, trade-log.jsonl, and positions.jsonl, commit with
   message "daily-summary {YYYY-MM-DD}", and push to the default branch.

Report back as the one daily message (<=6 lines): date + mode, EOD equity + cash, open positions
count, trades today, positions closed + realized P&L, and the journal path.
```

---

## 4. Weekly review

- **Name:** `SOP — Weekly review`
- **Model:** Sonnet — read-only analytics, lessons, and *suggested* tuning. No orders, no live
  decisions.
- **Schedule (cron, America/New_York):** `0 16 * * 5` — 16:00 ET Friday, after the close
- **Trigger:** Schedule

**Prompt:**

```text
You are running the AI Trading Agent SOP, weekly review phase, fully autonomously in a cloud
session. This phase is READ-ONLY over trade data — it never places orders and never edits
trade-log.jsonl or prior daily journals (append an Addendum rather than editing history).

1. Read ./CLAUDE.md and ./references/strategy.md for context.
2. Execute .claude/skills/weekly-review/SKILL.md end to end: read journal/{YYYY-MM-DD}.md for each
   trading day in the current Mon-Fri window and the full trade-log.jsonl; compute metrics
   (realized P&L total and per strategy via signal_source; P&L per theme via the theme field and
   themes.toml; win rate; exit-reason breakdown; open positions carried + unrealized P&L; and the
   benchmark check vs SPY over the same window — the goal is to beat the S&P 500); capture 3-5
   lessons; and write OPTIONAL tuning suggestions for strategy.md §A.4 (suggest only — never edit
   strategy.md or config.toml). Write journal/{YYYY-MM-DD}-weekly-review.md (Friday's date) with
   sections: Summary, P&L by Strategy, P&L by Theme, vs SPY Benchmark, Exit Reasons, Open
   Positions Carried (by theme), Lessons, Tuning Suggestions. Create a new file — never append to
   a prior week's.
3. Follow the skill's notification policy: ALWAYS send exactly one summary message.
4. FINALLY, persist state: stage the new journal/{YYYY-MM-DD}-weekly-review.md, commit with
   message "weekly-review {YYYY-MM-DD}", and push to the default branch.

Report back as the one weekly message (<=6 lines): week range, realized P&L (total + best/worst
strategy), win rate, trades count, vs SPY, and the weekly-review file path.
```

---

## Suggested order of operations

1. Add the **Robinhood MCP as a connector** on claude.ai and confirm it authenticates.
2. Set `NTFY_TOKEN` (and Robinhood secrets) as **env vars** on the routine environment.
3. Confirm `config.toml::mode` — start with `paper` to validate the full chain end to end before
   flipping `market-open` to `live`.
4. Create the four routines with the prompts + crons above; enable **unrestricted branch pushes**
   on each.
5. Use **Run now** on `pre-market` first, open the run, and confirm it pushed a journal commit to
   the default branch — that proves the state-persistence chain works before the others depend on
   it.
```
