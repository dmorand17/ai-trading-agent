# Data Sources

Catalog of every upstream feed the SOP touches. One section per source: purpose, endpoint, auth, freshness, cost, failure modes, parsing notes.

---

## A. Politician trades (Signal A)

### A.1 CapitolTrades.com — PRIMARY

- **Purpose:** Both-chamber feed of congressional Periodic Transaction Reports (PTRs), refreshed daily, free.
- **Endpoint:** `https://www.capitoltrades.com/trades`
  - Filter UI supports party, chamber, transaction type, date range, ticker.
  - Per-ticker view: `https://www.capitoltrades.com/issuers/{slug}`
- **Auth:** none.
- **Freshness:** daily, mirrors the underlying STOCK Act 30–45 day disclosure window.
- **Cost:** $0.
- **Access pattern:** no documented public API.
  - **Preferred:** fetch the HTML trades list and parse the `<table>` rows (server-rendered).
  - **Fallback:** Lambda Finance's Capitol Trades API wrapper — see `https://www.lambdafin.com/articles/capitol-trades-api`.
- **Required fields to extract per row:** politician name, party, chamber, ticker, transaction type (buy/sell/exchange), transaction date, reported date, amount range, asset type (stock/option/bond).
- **Failure modes:** layout changes break the scraper; Cloudflare challenge under heavy polling. Cap to ≤1 request / 10s, set a realistic browser `User-Agent`, and prefer once-per-hour polling.

### A.2 Quiver Quantitative — FALLBACK 1 (paid, robust)

- **Purpose:** Structured JSON for both chambers; deepest history (2016+).
- **Endpoint:**
  - Per-ticker historical: `https://api.quiverquant.com/beta/historical/congresstrading/{TICKER}`
  - Live feed: `https://api.quiverquant.com/beta/live/congresstrading`
- **Auth:** `Authorization: Bearer <QUIVER_API_KEY>`.
- **Freshness:** near real-time relative to PTR publication.
- **Cost:** ~$25/month entry tier.
- **Required env var:** `QUIVER_API_KEY`.
- **Response fields:** `Representative`, `ReportDate`, `TransactionDate`, `Ticker`, `Transaction`, `Range`, `House`, `Amount`, `Party`, `TickerType`, `ExcessReturn`, `PriceChange`, `SPYChange`.
- **Failure modes:** rate limit on free tier; quota burn if backfilling without cache.

### A.3 Finnhub — FALLBACK 2 (free)

- **Purpose:** Free aggregator JSON.
- **Endpoint:** `https://finnhub.io/api/v1/stock/congressional-trading?symbol={TICKER}&token={FINNHUB_API_KEY}`
- **Auth:** `token` query param.
- **Freshness:** lags Quiver; field coverage thinner.
- **Cost:** $0 on free tier; sharp rate limits.
- **Use case:** sanity-check / cross-validate the primary source.

### A.4 Official portals — FALLBACK 3 (authoritative, brittle)

- **House PTRs:** `https://disclosures-clerk.house.gov/FinancialDisclosure` — PDF downloads, no structured API.
- **Senate eFD:** `https://efdsearch.senate.gov/search/` — HTML search, cookie-based session, no structured API.
- **Use case:** dispute resolution / verifying a single record. Not a polling source.

---

## B. Corporate insider transactions (Signal B)

### B.1 SEC EDGAR Latest Filings Atom feed — PRIMARY

- **Purpose:** Continuous stream of every fresh Form 4.
- **Endpoint:** `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&output=atom`
  - Optional: add `&company=` for issuer filter, `&owner=include` to keep insiders.
- **Auth:** none, **but** mandatory `User-Agent` header:
  `User-Agent: "AI Trading Agent SOP — your_name your_email@domain.tld"`
  SEC blocks requests with default Python / curl agents.
- **Freshness:** refreshed every 10 minutes M–F, 06:00–22:00 ET. Form 4 must be filed within 2 business days of the transaction → discovery latency is small.
- **Cost:** $0.
- **Soft rate limit:** ~10 req/sec across all SEC.gov, per their fair-access policy.
- **Output shape:** Atom XML. Each `<entry>` has a `<title>`, `<updated>`, `<id>` (accession number), `<link>` to the filing folder.
- **Parsing handoff:** see `references/sec-edgar-form4.md` for the full XML schema and discovery recipe.

### B.2 EDGAR full-index — FALLBACK / backfill

- **Endpoint:** `https://www.sec.gov/Archives/edgar/full-index/{YYYY}/QTR{N}/form.idx`
- **Use case:** if the Atom feed misses or you need to backfill a missed day. Pipe-delimited text; filter for `Form Type == "4"`.

### B.3 Per-filing folder — XML retrieval

- **Pattern:** `https://www.sec.gov/Archives/edgar/data/{CIK}/{ACCESSION_NO_DASHES}/`
- **Locate ownership XML:** look for the `*.xml` file that is not `index.xml`. The naming varies (`wf-form4_...xml`, `xslF345X03/...`); always read the folder listing first.
- **Cache:** dedupe by accession number. Each accession is immutable.

### B.4 Commercial alternatives (optional)

- **sec-api.io** — paid, prepared JSON of every Form 3/4/5, query-able by code/role/ticker. Use only if EDGAR parsing becomes a bottleneck.

---

## C. Quotes & market state

### C.1 Robinhood MCP — PRIMARY (use during the SOP loop)

- **Purpose:** Live quote, position, account-equity reads inside the Agentic account.
- **Why this is primary:** order routing must use the same quote source as execution; Robinhood is authoritative for what the order will actually pay.
- **Tools:** discover at runtime via `tools/list`. The public docs do not enumerate the exact tool names; expect categories along the lines of:
  - read account / balances / positions
  - read order history / individual order
  - get quote / get level-1 market data
  - place / cancel / replace order
- **Constraint:** account must be the **dedicated Agentic account**, not the primary individual account.

### C.2 Free reference quote — SANITY CHECK ONLY

- **Endpoint:** any free EOD source (e.g. Yahoo Finance, Stooq).
- **Use case:** detect a stale Robinhood quote (spread > 1% vs reference). Never use as the order-routing price.

---

## D. Order execution

### D.1 Robinhood Agentic Trading MCP — SOLE EXECUTION VENUE

- **Connector URL:** `https://agent.robinhood.com/mcp/trading`
- **Transport:** HTTP, standard MCP.
- **Auth:** per-platform connector (Claude Code, Claude Desktop, ChatGPT, etc.). Stored outside this repo.
- **Eligibility:** active primary individual investing account in good standing; up to 10 dedicated Agentic accounts per user; mobile setup must be transferred to desktop for onboarding.
- **Supported order types:** the public doc says "available order types" but does not enumerate. **The SOP must call `tools/list` on session start and surface the actual tool surface** rather than assuming. The SOP defaults to limit orders only.
- **Asset classes confirmed:** US-listed equities. Options / crypto are not confirmed MCP-accessible; do not call them.
- **Safety features:** Robinhood provides a pre-action review step; the SOP layers its own pre-trade review + trade-log entry before invocation.

---

## E. Configuration & secrets

- **`mode.toml`** — repo root, source of truth for paper vs live, allowlist, manual-confirm. Schema in `references/rules.md`.
- **`.env`** — secrets only. Required keys depending on which fallbacks are wired: `QUIVER_API_KEY`, `FINNHUB_API_KEY`, `SEC_USER_AGENT`. Robinhood MCP auth is handled by the connector itself, not this file.
- **`.gitignore`** must include `.env`, `trade-log.jsonl`, `journal/`, and any cached feeds.

---

## F. Source-of-truth precedence (when sources disagree)

| Question | Authority |
| --- | --- |
| Did a politician actually file this trade? | Official portal (A.4) > Quiver (A.2) > CapitolTrades (A.1) |
| Did an insider actually buy? | EDGAR XML (B.3) — no aggregator beats it |
| What price will my order get? | Robinhood MCP quote (C.1) |
| What's my actual cash balance? | Robinhood MCP account read |
| Was my order filled? | Robinhood MCP order-status read |
