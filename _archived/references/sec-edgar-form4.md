# SEC EDGAR Form 4 — Discovery & XML Parsing

Reference for fetching, deduping, and parsing Form 4 filings so they can be scored by `references/insider-signal.md`.

> **Why Form 4 is the gold source:** Section 16 of the Exchange Act forces every officer, director, and 10% beneficial owner to disclose changes in ownership within **2 business days**. The filing is structured XML — no PDF parsing, no third-party aggregator drift. Discovery is free, real-time, and authoritative.

---

## 1. SEC fair-access compliance (do this first)

- **Mandatory `User-Agent` header on every request.** Format:
  `User-Agent: "AI Trading Agent SOP — Full Name email@domain.tld"`
  Plain Python / curl / generic agents are throttled or 403'd.
- **Soft rate limit:** ~10 requests / second across all of `sec.gov`. Stay below.
- **Backoff:** on `403` or `429`, exponential backoff starting at 1s. Do not hammer.
- **Cache aggressively.** Every accession number is immutable — store the parsed result and never re-fetch.

---

## 2. Discovery endpoints

### 2.1 Latest Filings Atom — PRIMARY (real-time)

```
https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&output=atom
```

Query params worth knowing:

| Param | Effect |
| --- | --- |
| `type=4` | Form 4 only (also accepts `4%2C5` for 4 and 5) |
| `output=atom` | machine-readable Atom XML |
| `company=` | filter to a single issuer name substring |
| `owner=include` | keep filings by insiders (default) |
| `count=40` | up to 100 |
| `start=0` | pagination |

**Cadence:** SEC refreshes every ~10 minutes, M–F 06:00–22:00 ET. Outside those hours the feed is stale.

**Atom entry shape (only the fields the SOP cares about):**

```xml
<entry>
  <title>4 - Doe Jane (0001999999) (Reporting)</title>
  <updated>2026-06-12T14:03:21-04:00</updated>
  <id>urn:tag:sec.gov,2008:accession-number=0001234567-26-000123</id>
  <link rel="alternate" type="text/html"
        href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK=0001234567&amp;..."/>
</entry>
```

- The accession number embedded in `<id>` is the stable dedupe key.
- The `<link>` does not point directly at the XML — it points at the filing index page. You'll resolve the XML in §3.

### 2.2 Daily index — FALLBACK / backfill

```
https://www.sec.gov/Archives/edgar/daily-index/{YYYY}/QTR{N}/form.{YYYYMMDD}.idx
```

- Pipe-delimited text.
- Columns: `Form Type | Company Name | CIK | Date Filed | File Name`.
- Filter where `Form Type == "4"`. Concat `https://www.sec.gov/Archives/` + `File Name` to reach the filing.
- Use when the Atom feed missed a window (overnight gap, outage).

### 2.3 Full-index — historical backfill

```
https://www.sec.gov/Archives/edgar/full-index/{YYYY}/QTR{N}/form.idx
```

Same shape as daily, but quarter-aggregated. Use for one-shot historical backfills only.

---

## 3. Resolving accession → ownership XML

Each accession number has a folder:

```
https://www.sec.gov/Archives/edgar/data/{CIK_int}/{ACCESSION_NO_DASHES}/
```

Where `ACCESSION_NO_DASHES` is the accession number with the dashes stripped (`0001234567-26-000123` → `000123456726000123`).

**Recipe:**

1. List the folder (HTML response — parse `<a href>` entries, or hit `…/index.json`).
2. Find the `*.xml` file whose name matches `*form4*.xml` or sits under the `xslF345*/` template path. Skip `index.xml` — that's the filing manifest, not the data.
3. GET the XML with the SOP `User-Agent`.

The `index.json` endpoint at `…/index.json` is the cleanest way to list:

```
GET https://www.sec.gov/Archives/edgar/data/1234567/000123456726000123/index.json
```

Returns `{"directory": {"item": [{"name": "wf-form4_172...xml", ...}, ...]}}`.

---

## 4. Ownership XML schema cheat sheet

Root element: `<ownershipDocument>` (also used for Forms 3 and 5 — check `<documentType>`).

```xml
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport>2026-06-10</periodOfReport>

  <issuer>
    <issuerCik>0001234567</issuerCik>
    <issuerName>ACME CORP</issuerName>
    <issuerTradingSymbol>ACME</issuerTradingSymbol>
  </issuer>

  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001999999</rptOwnerCik>
      <rptOwnerName>DOE JANE</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <isTenPercentOwner>0</isTenPercentOwner>
      <isOther>0</isOther>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>

  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-06-10</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>P</transactionCode>
        <equitySwapInvolved>0</equitySwapInvolved>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>42.17</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>120000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>

  <derivativeTable> <!-- options, RSUs, etc. — skip for Signal B --> </derivativeTable>

  <footnotes>
    <footnote id="F1">Acquired in open-market purchase.</footnote>
  </footnotes>

  <ownerSignature>
    <signatureName>Jane Doe</signatureName>
    <signatureDate>2026-06-11</signatureDate>
  </ownerSignature>
</ownershipDocument>
```

**Notes:**
- `<reportingOwner>` may repeat (group filings — one XML, several insiders).
- `<nonDerivativeTransaction>` may repeat (multiple lots same day).
- `<directOrIndirectOwnership>` value `I` (indirect) often means via trust / family entity — still counts for Section 16 disclosure but worth surfacing.
- `<sharesOwnedFollowingTransaction>` is useful for sanity-checking the buy size relative to existing stake.

---

## 5. Transaction code reference

The single most important field is `<transactionCode>`. Trust hierarchy for **buy-direction** signals:

| Code | Meaning | Signal B treatment |
| --- | --- | --- |
| **P** | Open-market or private **purchase** | **TRUST — only buy code we keep** |
| S | Open-market or private sale | inverse signal — kills a cluster |
| A | Grant / award | ignore (mechanical) |
| M | Exercise of derivative (in-/at-money) | ignore (mechanical) |
| F | Payment of withholding tax via shares | ignore |
| G | Bona fide gift | ignore |
| J | Other (footnote required) | read footnote; default ignore |
| V | Voluntarily reported early | modifier — keep if co-occurs with P |
| K | Equity swap | ignore (derivative) |
| U | Tender disposition (change of control) | ignore |
| C | Conversion of derivative | ignore |
| X | Exercise of in-/at-money derivative | ignore |
| O | Exercise of out-of-money derivative | ignore |
| E | Expiration of short derivative | ignore |
| H | Expiration / cancellation of long derivative | ignore |
| L | Small acquisition under Rule 16a-6 | ignore (immaterial) |
| W | Acquisition by will / inheritance | ignore (not directional) |
| Z | Voting trust deposit / withdrawal | ignore |

**Composite codes** (e.g. `S/K`, `P/K`): split on `/` and treat as the primary code listed; the second is a modifier. A `P/K` is still a purchase but came via an equity swap — treat with suspicion (drop unless footnote clarifies it's a real cash buy).

---

## 6. Parsing recipe (pseudocode)

```python
# 1. Pull recent filings
atom = http_get(ATOM_URL, headers={"User-Agent": SEC_USER_AGENT})
entries = parse_atom(atom)  # list of {accession, updated, html_link}

# 2. Dedupe against cache
new_accessions = [e for e in entries if e.accession not in cache]

# 3. For each new accession, find the ownership XML
for entry in new_accessions:
    folder = build_folder_url(entry.accession)
    listing = http_get(folder + "index.json", headers=...)
    xml_name = pick_form4_xml(listing)  # *.xml that is not index.xml
    xml = http_get(folder + xml_name, headers=...)

    doc = parse_xml(xml)
    if doc.documentType != "4":
        continue

    issuer = {
        "cik": doc.issuer.issuerCik,
        "name": doc.issuer.issuerName,
        "ticker": doc.issuer.issuerTradingSymbol,
    }

    for owner in doc.reportingOwner_list:
        role = derive_role(owner.reportingOwnerRelationship)  # CEO/CFO/Director/...
        for txn in doc.nonDerivativeTable.transactions:
            if txn.transactionCode != "P":
                continue
            if txn.acquiredDisposedCode != "A":
                continue
            record = {
                "accession": entry.accession,
                "ticker": issuer["ticker"],
                "issuer_cik": issuer["cik"],
                "insider_name": owner.rptOwnerName,
                "role": role,
                "transaction_date": txn.transactionDate,
                "shares": float(txn.transactionShares),
                "price": float(txn.transactionPricePerShare),
                "filed_at": entry.updated,
            }
            yield record  # feed to insider-signal scorer
    cache.mark_processed(entry.accession)
```

Use `lxml` for speed or `xml.etree.ElementTree` to avoid the C dependency. Both handle the schema fine.

---

## 7. Edge cases

- **No `issuerTradingSymbol`:** rare but happens with newly-IPO'd issuers or some foreign-private issuers. Skip — we trade by ticker.
- **Form 4/A (amendment):** `<documentType>4/A</documentType>`. Treat as an update: re-key by `accession` and replace the prior record in cache.
- **Multiple reporting owners on one XML:** count each as a distinct insider for clustering purposes, but flag if they share the same employer family (trust / family LP) — see §5 of `insider-signal.md`.
- **Indirect ownership only:** if every transaction has `directOrIndirectOwnership=I`, the buy is via a trust or LLC — still counts but `bonuses_applied` should not include cross-role diversity.
- **Pre-arranged 10b5-1 plan:** Form 4 has a checkbox / flag for 10b5-1; pre-arranged buys are *less* informative than spontaneous ones. Apply a `−5` penalty in scoring (handled inside `insider-signal.md` if you wire it).
