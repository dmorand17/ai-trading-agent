# Signal A — Politician Clusters

Detect and score clusters of **buys** in the same ticker reported across multiple members of Congress within a tight window.

> **Why this signal works:** committee assignments expose members to non-public legislative trajectories (subsidies, contracts, regulatory shifts). Clusters across multiple offices reduce the "single-member spouse-broker" noise floor. The signal is structurally laggy (STOCK Act PTRs publish 30–45 days after the trade) — sizing reflects that.

## 1. Inputs

A normalized list of PTR rows from `references/data-sources.md` (CapitolTrades primary). Each row needs:

| Field | Notes |
| --- | --- |
| `politician_id` | stable name or slug |
| `chamber` | `house` or `senate` |
| `party` | `D`, `R`, `I` |
| `ticker` | US-listed common only — drop options, bonds, mutual funds |
| `transaction_type` | `buy` / `sell` / `exchange` |
| `transaction_date` | the actual trade date — **use this for windowing** |
| `report_date` | the disclosure date — use only for freshness checks |
| `amount_range` | bucketed dollar range, e.g. `"$1,001 - $15,000"` |
| `asset_type` | `stock` / `option` / `bond` / `etf` — keep `stock` only |

## 2. Cluster definition (tunable)

A **Signal A cluster** for ticker `T` exists when **all** of the following hold:

1. **Distinct members:** ≥ `MIN_MEMBERS` distinct `politician_id` (default `3`) bought `T`.
2. **Tight window:** all qualifying `transaction_date` values fall within `WINDOW_TRADING_DAYS` (default `10`).
3. **Buy-only:** every row has `transaction_type == "buy"`. A `sell` from any member in the same window **disqualifies** the cluster.
4. **Equity-only:** every row has `asset_type == "stock"`. Mixed option clusters are scored separately and currently skipped.
5. **Freshness:** the median `transaction_date` is within `MAX_AGE_TRADING_DAYS` (default `30`). Older clusters have decayed edge — drop.

If any condition fails → **no signal**.

## 3. Scoring (0 – 100)

```
score = base + member_score + amount_score + bonuses − penalties
```

### 3.1 Base

`base = 20` when the cluster condition is met.

### 3.2 Member score

Per distinct member: `+5`. Cap at `+30`.

### 3.3 Amount score

Map each member's `amount_range` to its midpoint, sum them, score from this table:

| Aggregate cluster $ | Points |
| --- | --- |
| < $50K | +0 |
| $50K – $250K | +5 |
| $250K – $1M | +10 |
| $1M – $5M | +20 |
| > $5M | +25 |

If a row's range is the top bucket `"$5,000,001 - $25,000,000"` or higher, use $10M as the midpoint (conservative).

### 3.4 Bonuses

- **Bipartisan (+10):** at least one buyer from each of the two major parties.
- **Committee–sector overlap (+10):** at least one member sits on a committee aligned with the ticker's sector. Map (extensible):
  - Defense names ↔ House/Senate Armed Services
  - Pharma / biotech ↔ Senate HELP / House Energy & Commerce
  - Banks / fintech ↔ House Financial Services / Senate Banking
  - Energy ↔ Senate Energy & Natural Resources
- **Repeat-outperformer member (+5):** any cluster member's all-time `ExcessReturn` (from Quiver if available) > +10% vs SPY. Cap once even if multiple qualify.
- **Bicameral (+5):** buyers from both chambers.

### 3.5 Penalties

- **Spouse-only filings (−10):** if `≥ 50%` of the rows are flagged as spouse / dependent rather than the member directly. Many feeds expose this in the filer name; if not parseable, skip the penalty.
- **Stale disclosure (−5 per 5 trading days):** for every 5 trading days the median `transaction_date` is older than `MAX_AGE_TRADING_DAYS / 2`. Stacks linearly.
- **Amendment reversal (−20):** if an earlier disclosed buy in the same window has since been amended out, treat the cluster with extreme suspicion.

### 3.6 Hard floor / ceiling

`score = max(0, min(100, score))`.

## 4. Conviction tier mapping

| Score | Tier | Action (per `references/rules.md`) |
| --- | --- | --- |
| 0 – 39 | skip | no trade |
| 40 – 59 | low | enter at 0.5% sizing |
| 60 – 79 | medium | enter at 1.0% sizing |
| 80 – 100 | high | enter at 2.0% sizing |

## 5. Disqualifiers (immediate skip regardless of score)

- Ticker is on the user's blocklist (see `mode.toml` `block_tickers`, if defined).
- Position cap from `rules.md` already breached for this ticker.
- A Form 4 **sale** by a Section-16 officer (CEO/CFO/Director) in the same ticker has hit in the last 30 days. Insider selling overrides political enthusiasm.
- The ticker has had a delisting / bankruptcy / going-private announcement in the last 30 days.
- Average daily dollar volume < $5M (illiquid).

## 6. Combined-signal interaction

If a Signal B cluster (insiders) also fires on the same ticker within ±30 days of this cluster's median transaction date → upgrade conviction by **one tier** (capped at high). See `references/rules.md` §4.

## 7. Output shape (handed to `rules.md`)

```json
{
  "signal_source": "A",
  "ticker": "XYZ",
  "score": 72,
  "tier": "medium",
  "cluster_members": ["Rep. Foo", "Sen. Bar", "Rep. Baz"],
  "cluster_window_days": 10,
  "aggregate_amount_midpoint_usd": 425000,
  "median_transaction_date": "2026-05-15",
  "bonuses_applied": ["bipartisan", "committee_overlap:defense"],
  "penalties_applied": []
}
```

## 8. Knobs (centralize at top of any implementation)

```toml
[signal_a]
min_members = 3
window_trading_days = 10
max_age_trading_days = 30
min_score_to_trade = 40
```
