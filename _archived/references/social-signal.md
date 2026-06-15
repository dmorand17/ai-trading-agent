# Signal C — Social Media Clusters (DRAFT — not yet active)

> **Status:** draft / not wired in. The SOP will not place trades on Signal C until the user explicitly activates it by setting `signal_c.active = true` in `mode.toml`.

Detect and score clusters of **bullish social-media activity** around the same ticker within a tight window. Social signals are notoriously noisy — this file documents the design so the user can iterate on sources and thresholds before flipping it live.

---

## 1. Hypothesis

Social conversation often **precedes** large retail flow (and occasionally institutional positioning). Tradeable variants of this signal:

- **Velocity surge:** mentions/hour for a ticker spike >Nσ above its 30-day baseline.
- **Influencer alignment:** multiple high-quality, low-following-overlap accounts mention the same ticker bullishly within a short window.
- **Subreddit cluster:** a single ticker rockets up the day's r/wallstreetbets / r/stocks / r/investing post counts.

Signal C is **always** noisier than A or B. Treat it as a tier-downgrade signal until proven otherwise: a Signal C alone enters at the *low* tier ceiling regardless of score.

---

## 2. Candidate sources (TBD — user to confirm)

### 2.1 Reddit

- **Pushshift-style aggregators:** `https://api.pushshift.io/reddit/search/comment` (intermittently up; check status before depending on it).
- **Official Reddit API:** `https://oauth.reddit.com/r/{subreddit}/new.json` — requires registered app + OAuth token. Rate limit: 60 req/min/user.
- **ApeWisdom:** `https://apewisdom.io/api/v1.0/filter/all-stocks` — already aggregates mentions/comments/sentiment across r/wallstreetbets, r/stocks, r/investing, etc. Free, JSON. Probably the lowest-effort starting point.
- **Subreddits worth tracking:**
  - r/wallstreetbets (retail momentum, ridiculous variance)
  - r/stocks (slightly higher signal-to-noise)
  - r/investing (slowest, often most useful)
  - r/options (sentiment that often leads underlying)
  - r/SecurityAnalysis (low volume, high quality)

### 2.2 Twitter / X

- **Official API v2:** `https://api.twitter.com/2/tweets/search/recent` — requires paid tier for any useful query volume.
- **Cashtag search:** filter for `$TICKER` mentions. Cashtags are explicit, so noise from a name collision (e.g. `Apple` the fruit) is reduced.
- **Likely-useful accounts to seed an influencer list (user to curate):**
  - Buy-side analysts who post original DD
  - Sell-side analysts with public X accounts
  - Independent finance writers with a published track record
  - Avoid: pump-and-dump aggregators, "1000% gain" reply guys, paid promotion accounts
- **List management:** maintain a hand-curated list in `social-influencers.json` (TBD schema). Bootstrap from following lists of known-credible analysts.

### 2.3 StockTwits

- **Endpoint:** `https://api.stocktwits.com/api/2/streams/symbol/{TICKER}.json`
- **Auth:** none for read.
- **Sentiment tags:** users self-tag posts `bullish` / `bearish`. Aggregating these gives a fast directional read but is highly gameable.

### 2.4 Other

- **Google Trends:** ticker search-volume spikes. Coarse but free.
- **Specialist data vendors:** Quiver Quantitative (already in `references/data-sources.md`) and Unusual Whales expose mentions / sentiment endpoints if you're willing to pay.

---

## 3. Cluster definition (proposed; tune after dry-run)

A **Signal C cluster** for ticker `T` exists when **all** of:

1. **Volume:** mentions over the trailing 6 hours ≥ `MENTIONS_THRESHOLD` (per-source baseline; default = 3× rolling 30-day median).
2. **Independence:** the spike is observed in ≥ `MIN_SOURCES` distinct sources (default `2`). E.g., both ApeWisdom (Reddit) and StockTwits.
3. **Sentiment:** net bullish ratio ≥ 0.6 across counted mentions.
4. **No catalyst-fade:** mentions did **not** spike *because* of an obvious news event already priced in (acquisition announcement, earnings beat — those are reactive, not predictive). Cross-check against a news headline scan.

If any condition fails → **no signal**.

---

## 4. Scoring (proposed)

```
score = base + velocity_score + independence_score + sentiment_score − noise_penalties
```

### 4.1 Base

`base = 15` when the cluster condition is met (lower than A's 20 and B's 25 because base reliability is lower).

### 4.2 Velocity score

Per-σ above 30-day baseline:

| σ above baseline | Points |
| --- | --- |
| 3–4 | +5 |
| 4–6 | +10 |
| 6–10 | +15 |
| > 10 | +20 |

(>10σ is often a *fade*, not a buy — see §6.)

### 4.3 Independence score

- 2 independent sources: +5
- 3 independent sources: +10
- 4+ independent sources: +15

### 4.4 Sentiment score

- Net bullish ratio 0.6–0.75: +5
- 0.75–0.9: +10
- >0.9: +5 (suspiciously uniform — often coordinated)

### 4.5 Noise penalties

- **Pump-pattern detected (−25):** sudden mention spike from accounts with low historical activity and high follower overlap. Single biggest false-positive class for retail-driven social signals.
- **Penny stock / micro-cap (−20):** market cap < $300M. Social pump risk is disproportionately high here.
- **Day-of earnings (−15):** the move is event-driven, not directional.
- **Single-source dominance (−10):** ≥ 70% of mentions come from one source (usually means one viral post, not a real cluster).

### 4.6 Hard floor / ceiling

`score = max(0, min(100, score))`.

---

## 5. Conviction tier mapping (capped at `low` while signal is in trial)

| Score | Tier when `signal_c.trial = true` | Tier when fully active |
| --- | --- | --- |
| 0 – 49 | skip | skip |
| 50 – 69 | skip (log only) | low |
| 70 – 84 | low | medium |
| 85 – 100 | low | high |

**Default behavior:** trial mode. Signal C alone produces low conviction at most. Signal C **only counts** for combined-signal bonus (§5 of `rules.md`) once the user flips `signal_c.trial = false`.

---

## 6. Known failure modes

- **Pump-and-dump rings.** Coordinated bot/account networks inflate mention counts on micro-caps. Penalty in §4.5 helps but doesn't eliminate.
- **Sentiment reversal at peak.** Once retail attention is broad enough to register on Google Trends or financial news, the trade is usually too late.
- **Cashtag collisions.** `$X` (US Steel), `$F` (Ford) — short tickers also appear in non-financial contexts. Require ≥ 2 ticker-context features per mention (cashtag + a finance keyword) before counting.
- **Echo loops.** A single Bloomberg headline can produce thousands of derivative posts that look like a cluster but are one signal. Dedupe by post-content hash and parent-chain when possible.
- **Bot farms in subreddits.** Account age, karma, and posting history are first-pass filters. ApeWisdom does some of this for you; the official Reddit API does not.

---

## 7. Activation checklist (do all before flipping `signal_c.active = true`)

1. Pick one source first (ApeWisdom is easiest). Run signal generation in parallel with A and B for **≥ 30 trading days** in paper mode.
2. Backtest the trial-mode scoring against the last 12 months of public Reddit data. Look for:
   - Mean and median forward return at 5/10/30 trading days
   - Hit rate above 50% across at least 50 historical clusters
   - Drawdown profile
3. Decide between trial-mode (Signal C alone → low) and full activation (Signal C alone → up to high).
4. If full activation: add to `mode.toml`:
   ```toml
   [signal_c]
   active = true
   trial = false
   sources = ["apewisdom", "stocktwits"]
   ```
5. Update `references/data-sources.md` §A or add §G with the activated source details (auth, rate limits, env vars).
6. Update `references/rules.md` §5 to include `"C"` and combined variants in `signal_source`.

---

## 8. Output shape (when active — handed to `rules.md`)

```json
{
  "signal_source": "C",
  "ticker": "XYZ",
  "score": 68,
  "tier": "low",
  "sources": ["apewisdom", "stocktwits"],
  "mentions_6h": 420,
  "baseline_mentions_6h": 38,
  "sigma_above_baseline": 6.7,
  "bullish_ratio": 0.72,
  "noise_flags": ["single_source_dominance:apewisdom"],
  "bonuses_applied": [],
  "penalties_applied": ["single_source_dominance"]
}
```

---

## 9. Knobs (proposed defaults — tune during trial)

```toml
[signal_c]
active = false             # master switch; SOP ignores Signal C entirely when false
trial = true               # trial-mode tier cap (see §5)
min_sources = 2
mentions_sigma_threshold = 3
bullish_ratio_threshold = 0.6
min_score_to_trade = 70    # higher than A/B because base data is noisier
sources = ["apewisdom"]    # start with one
```

---

## 10. Open questions for the user

These are the decisions blocking activation. Capture answers when you're ready:

1. Which one source to start with? (Recommendation: ApeWisdom — free, no auth, already aggregates Reddit.)
2. Are you willing to pay for Twitter API access, or skip Twitter for now?
3. Do you want a curated influencer list, or pure crowd-aggregate signals?
4. Is Signal C allowed to fire **alone**, or only as a tier-bumper for A or B?
5. What's the smallest acceptable market cap? (Default $300M filter is conservative for retail-social signals.)
