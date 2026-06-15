# Signal B — Insider Clusters

Detect and score clusters of **open-market purchases** by Section-16 corporate insiders (officers, directors, 10% owners) in the same issuer within a tight window.

> **Why this signal works:** insiders have the deepest, most-current visibility into business performance. The single hard-to-fake action is *spending their own money* to buy stock on the open market. The literature on cluster buying (≥2 insiders buying near-simultaneously) is one of the most durable equity edges. Form 4 must be filed within 2 business days of the trade, so discovery lag is small.

## 1. Inputs

Parsed Form 4 records produced via `references/sec-edgar-form4.md`. Each record needs:

| Field | Source XPath (approx.) |
| --- | --- |
| `accession_no` | from Atom entry id |
| `issuer_cik` | `issuer/issuerCik` |
| `issuer_name` | `issuer/issuerName` |
| `ticker` | `issuer/issuerTradingSymbol` |
| `insider_name` | `reportingOwner/reportingOwnerId/rptOwnerName` |
| `is_director` | `reportingOwner/reportingOwnerRelationship/isDirector` |
| `is_officer` | `reportingOwner/reportingOwnerRelationship/isOfficer` |
| `officer_title` | `reportingOwner/reportingOwnerRelationship/officerTitle` |
| `is_ten_percent_owner` | `reportingOwner/reportingOwnerRelationship/isTenPercentOwner` |
| `transaction_code` | `nonDerivativeTransaction/transactionCoding/transactionCode` |
| `acquired_disposed_code` | `nonDerivativeTransaction/transactionAmounts/transactionAcquiredDisposedCode` |
| `transaction_date` | `nonDerivativeTransaction/transactionDate/value` |
| `transaction_shares` | `nonDerivativeTransaction/transactionAmounts/transactionShares/value` |
| `transaction_price_per_share` | `nonDerivativeTransaction/transactionAmounts/transactionPricePerShare/value` |

## 2. Per-row filter (apply BEFORE clustering)

Keep a row only if **all** of:

1. `transaction_code == "P"` — open-market purchase. The only discretionary buy code.
2. `acquired_disposed_code == "A"` — acquired (defensive sanity check; P implies A).
3. `transaction_shares > 0` and `transaction_price_per_share > 0`.
4. Row sits in `<nonDerivativeTable>`. Skip derivative-table rows entirely for this signal — option exercises are not a conviction buy.

Reject everything else. **Explicitly reject** codes:

| Code | Meaning | Why reject |
| --- | --- | --- |
| A | Grant / award | not a discretionary buy |
| M | Option exercise | mechanical |
| F | Tax withholding | not directional |
| G | Gift | not directional |
| J | Other | read footnote — almost always noise |
| S | Sale | invalidates a buy cluster, see §5 |
| V | Voluntary early disclosure | a modifier, can co-occur with P — keep if P present |
| K | Equity swap | derivative |
| U | Tender disposition | M&A mechanics |

## 3. Cluster definition (tunable)

A **Signal B cluster** for `issuer_cik` exists when **all** of the following hold:

1. **Distinct insiders:** ≥ `MIN_INSIDERS` distinct `insider_name` (default `2`) bought.
2. **Tight window:** all qualifying `transaction_date` values fall within `WINDOW_TRADING_DAYS` (default `10`).
3. **Weighted threshold:** the weighted insider count clears `MIN_WEIGHTED` (default `4.0`). Weights:
   - CEO or CFO → `3.0`
   - President, COO, Chairman, Director → `2.0`
   - Other officer → `1.5`
   - 10% beneficial owner → `1.0`
   (Resolve from `officer_title` keywords; if `is_director=true` and no officer title, use `2.0`.)
4. **Dollar floor:** `sum(transaction_shares × transaction_price_per_share) ≥ MIN_DOLLARS` (default `$100,000`). Kills token "show purchases".
5. **No invalidating sale:** no `transaction_code == "S"` from the same insider on the same ticker in the cluster window.

If any condition fails → **no signal**.

## 4. Scoring (0 – 100)

```
score = base + insider_score + dollar_score + bonuses − penalties
```

### 4.1 Base

`base = 25` when the cluster condition is met.

### 4.2 Insider score

`+5` per distinct insider, cap `+25`.
Additionally: `+10` if the cluster includes a CEO **and** a CFO (rare and strong).

### 4.3 Dollar score

| Aggregate cluster $ | Points |
| --- | --- |
| $100K – $250K | +5 |
| $250K – $1M | +10 |
| $1M – $5M | +15 |
| > $5M | +20 |

### 4.4 Bonuses

- **52-week-low purchase (+10):** median `transaction_price_per_share` is within 10% of the issuer's 52-week low.
- **Cross-role diversity (+5):** cluster contains at least one officer **and** at least one outside director.
- **Recent earnings (+5):** the cluster sits within 5 trading days *after* an earnings release (insiders buying through the open window post-earnings is a strong tell).
- **Cluster-on-cluster (+10):** a separate qualifying cluster already fired on this issuer in the last 90 days and the stock has not yet recovered to that prior cluster's median price.

### 4.5 Penalties

- **CEO/CFO selling in same 30 days (−25):** even a single `S` filing from a CEO/CFO in the last 30 days knee-caps a buy cluster. If big enough, prefer to skip outright (see §5).
- **Late filing (−5):** any row where `filed_date − transaction_date > 2 business days`. Late filers are noisier.
- **Footnote-heavy (−5):** `<footnote>` count > 3 on the row — usually means special-situation accounting.

### 4.6 Hard floor / ceiling

`score = max(0, min(100, score))`.

## 5. Disqualifiers (immediate skip regardless of score)

- Any CEO or CFO `S` (sale) filing in the same ticker within the cluster window.
- Issuer is in bankruptcy, going-private, or delisting.
- Average daily dollar volume < $5M.
- Ticker is on the user's blocklist.
- All qualifying buyers belong to the same family / related entity (per cross-reference of `reportingOwnerId` CIKs).

## 6. Conviction tier mapping

| Score | Tier | Action (per `references/rules.md`) |
| --- | --- | --- |
| 0 – 44 | skip | no trade |
| 45 – 64 | low | enter at 0.5% sizing |
| 65 – 84 | medium | enter at 1.0% sizing |
| 85 – 100 | high | enter at 2.0% sizing |

(Thresholds are higher than Signal A because the data is faster and more reliable — we can afford to be pickier.)

## 7. Combined-signal interaction

If a Signal A cluster fires on the same ticker within ±30 days of this cluster's median transaction date → upgrade conviction by **one tier** (capped at high). See `references/rules.md` §4.

## 8. Output shape (handed to `rules.md`)

```json
{
  "signal_source": "B",
  "ticker": "XYZ",
  "issuer_cik": "0001234567",
  "score": 78,
  "tier": "medium",
  "cluster_insiders": [
    {"name": "Jane Doe", "role": "CEO", "weight": 3.0, "amount_usd": 250000},
    {"name": "John Roe", "role": "Director", "weight": 2.0, "amount_usd": 180000}
  ],
  "weighted_count": 5.0,
  "aggregate_amount_usd": 430000,
  "cluster_window_days": 10,
  "median_transaction_date": "2026-06-03",
  "bonuses_applied": ["52w_low"],
  "penalties_applied": []
}
```

## 9. Knobs (centralize at top of any implementation)

```toml
[signal_b]
min_insiders = 2
min_weighted = 4.0
window_trading_days = 10
min_dollars = 100000
min_score_to_trade = 45
```
