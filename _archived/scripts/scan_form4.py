#!/usr/bin/env python3
"""
Form 4 insider-cluster scanner — Signal B (references/insider-signal.md).

Pulls the SEC EDGAR Latest Filings Atom feed, pairs Reporting+Issuer entries
by accession, identifies issuers with >=2 distinct insider filings, fetches
each filing's ownership XML, keeps only open-market purchases (transaction
code 'P'), and applies the cluster definition + scoring from
references/insider-signal.md.

Stdlib only. Read-only. Writes one JSON file per run to signals/.

Usage:
  SEC_USER_AGENT="Your Name your@email.com" python3 scripts/scan_form4.py
  SEC_USER_AGENT="Your Name your@email.com" python3 scripts/scan_form4.py --count 200 --verbose

Output:
  stdout: human-readable summary
  signals/form4-{YYYY-MM-DD}.json: structured signals for the SOP agent

Exit codes:
  0: success (may include zero qualifying clusters)
  1: misconfiguration (missing SEC_USER_AGENT)
  2: network / parse error
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNALS_DIR = REPO_ROOT / "signals"

ATOM_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_HOST = "https://www.sec.gov"

MIN_INSIDERS = 2
WINDOW_TRADING_DAYS = 10
MIN_DOLLARS = 100_000
MIN_SCORE_TO_TRADE = 45

ROLE_WEIGHTS = {
    "ceo": 3.0, "chief executive": 3.0,
    "cfo": 3.0, "chief financial": 3.0,
    "coo": 2.0, "chief operating": 2.0,
    "president": 2.0,
    "chairman": 2.0,
    "chair": 2.0,
    "director": 2.0,
    "officer": 1.5,
    "10% owner": 1.0,
}

RATE_LIMIT_SECONDS = 0.12

_last_request_at = 0.0


def get_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        print(
            "ERROR: SEC_USER_AGENT environment variable is required.\n"
            'Example: SEC_USER_AGENT="Your Name your@email.com"',
            file=sys.stderr,
        )
        sys.exit(1)
    return ua


def sec_get(url: str, ua: str, retries: int = 3) -> bytes:
    global _last_request_at
    for attempt in range(retries):
        elapsed = time.time() - _last_request_at
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)
        try:
            req = Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
            with urlopen(req, timeout=30) as resp:
                _last_request_at = time.time()
                return resp.read()
        except HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                backoff = 2 ** attempt
                print(f"  ! {e.code} on {url}, backing off {backoff}s", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise
        except URLError as e:
            if attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            raise
    raise RuntimeError(f"Exceeded retries fetching {url}")


def parse_atom(xml_bytes: bytes) -> list[dict]:
    text = xml_bytes.decode("iso-8859-1", errors="replace")
    entries = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)
    rows = []
    title_re = re.compile(
        r"4(?:/A)?\s*-\s*(.+?)\s*\((\d+)\)\s*\((Issuer|Reporting)\)"
    )
    for e in entries:
        title_m = re.search(r"<title>(.*?)</title>", e)
        accn_m = re.search(r"accession-number=([\d-]+)", e)
        updated_m = re.search(r"<updated>(.*?)</updated>", e)
        href_m = re.search(r'href="(.*?)"', e)
        if not (title_m and accn_m and updated_m and href_m):
            continue
        m = title_re.match(title_m.group(1))
        if not m:
            continue
        name, cik, kind = m.groups()
        rows.append({
            "kind": kind,
            "name": name.strip(),
            "cik": cik,
            "accn": accn_m.group(1),
            "updated": updated_m.group(1),
            "href": href_m.group(1),
        })
    return rows


def pair_filings(rows: list[dict]) -> list[dict]:
    by_accn: dict[str, dict] = defaultdict(dict)
    for r in rows:
        by_accn[r["accn"]][r["kind"]] = r
    filings = []
    for accn, parts in by_accn.items():
        if "Issuer" in parts and "Reporting" in parts:
            filings.append({
                "accn": accn,
                "issuer_name": parts["Issuer"]["name"],
                "issuer_cik": parts["Issuer"]["cik"],
                "reporter_name": parts["Reporting"]["name"],
                "reporter_cik": parts["Reporting"]["cik"],
                "updated": parts["Issuer"]["updated"],
                "index_href": parts["Issuer"]["href"],
            })
    return filings


def candidate_issuer_clusters(filings: list[dict]) -> dict[str, list[dict]]:
    by_issuer: dict[str, list[dict]] = defaultdict(list)
    for f in filings:
        by_issuer[f["issuer_cik"]].append(f)
    return {
        cik: fs
        for cik, fs in by_issuer.items()
        if len({f["reporter_cik"] for f in fs}) >= MIN_INSIDERS
    }


def filing_folder_url(index_href: str) -> str:
    href = index_href if index_href.startswith("http") else SEC_HOST + index_href
    return href.rsplit("/", 1)[0] + "/"


def resolve_xml_url(folder_url: str, ua: str) -> str | None:
    try:
        listing = sec_get(folder_url + "index.json", ua)
    except Exception as e:
        print(f"  ! folder listing failed for {folder_url}: {e}", file=sys.stderr)
        return None
    data = json.loads(listing.decode())
    items = data.get("directory", {}).get("item", [])
    candidates = [
        i["name"] for i in items
        if i["name"].endswith(".xml") and i["name"] != "index.xml" and "primary_doc" not in i["name"].lower() or i["name"].lower().endswith("primary_doc.xml")
    ]
    if not candidates:
        candidates = [
            i["name"] for i in items
            if i["name"].endswith(".xml") and i["name"] != "index.xml"
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (0 if "form4" in n.lower() or "primary_doc" in n.lower() else 1, len(n)))
    return folder_url + candidates[0]


def text_or_none(elem, path) -> str | None:
    found = elem.find(path)
    if found is None:
        return None
    val = found.find("value")
    if val is not None and val.text is not None:
        return val.text.strip()
    if found.text is not None:
        return found.text.strip()
    return None


def parse_form4_xml(xml_bytes: bytes) -> dict | None:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return {"_error": f"parse: {e}"}

    doc_type = root.findtext("documentType", "").strip()
    if doc_type not in ("4", "4/A"):
        return None

    issuer = root.find("issuer")
    ticker = (issuer.findtext("issuerTradingSymbol") or "").strip() if issuer is not None else ""

    insiders = []
    for ro in root.findall("reportingOwner"):
        roi = ro.find("reportingOwnerId")
        if roi is None:
            continue
        name = (roi.findtext("rptOwnerName") or "").strip()
        cik = (roi.findtext("rptOwnerCik") or "").strip()
        rel = ro.find("reportingOwnerRelationship")
        is_director = rel is not None and (rel.findtext("isDirector") or "0").strip() in ("1", "true")
        is_officer = rel is not None and (rel.findtext("isOfficer") or "0").strip() in ("1", "true")
        is_tenpct = rel is not None and (rel.findtext("isTenPercentOwner") or "0").strip() in ("1", "true")
        officer_title = (rel.findtext("officerTitle") or "").strip() if rel is not None else ""
        insiders.append({
            "name": name,
            "cik": cik,
            "is_director": is_director,
            "is_officer": is_officer,
            "is_ten_percent_owner": is_tenpct,
            "officer_title": officer_title,
            "role": derive_role(is_director, is_officer, is_tenpct, officer_title),
        })

    purchases = []
    table = root.find("nonDerivativeTable")
    if table is not None:
        for txn in table.findall("nonDerivativeTransaction"):
            code = text_or_none(txn, "transactionCoding/transactionCode")
            acq = text_or_none(txn, "transactionAmounts/transactionAcquiredDisposedCode")
            txn_date = text_or_none(txn, "transactionDate")
            shares = text_or_none(txn, "transactionAmounts/transactionShares")
            price = text_or_none(txn, "transactionAmounts/transactionPricePerShare")
            if code != "P" or acq != "A":
                continue
            try:
                shares_f = float(shares or 0)
                price_f = float(price or 0)
            except ValueError:
                continue
            if shares_f <= 0 or price_f <= 0:
                continue
            purchases.append({
                "transaction_date": txn_date,
                "shares": shares_f,
                "price": price_f,
                "amount_usd": shares_f * price_f,
            })

    return {
        "ticker": ticker,
        "insiders": insiders,
        "purchases": purchases,
    }


def derive_role(is_director: bool, is_officer: bool, is_ten_pct: bool, officer_title: str) -> str:
    title = officer_title.lower()
    if "chief executive" in title or re.search(r"\bceo\b", title):
        return "CEO"
    if "chief financial" in title or re.search(r"\bcfo\b", title):
        return "CFO"
    if "chief operating" in title or re.search(r"\bcoo\b", title):
        return "COO"
    if "president" in title:
        return "President"
    if "chairman" in title or "chair of the board" in title:
        return "Chairman"
    if is_officer:
        return officer_title or "Officer"
    if is_director:
        return "Director"
    if is_ten_pct:
        return "10% Owner"
    return "Other"


def role_weight(role: str) -> float:
    r = role.lower()
    if "ceo" in r or "chief executive" in r:
        return 3.0
    if "cfo" in r or "chief financial" in r:
        return 3.0
    if r in ("director", "president", "coo", "chairman"):
        return 2.0
    if "officer" in r:
        return 1.5
    if "10%" in r or "ten percent" in r:
        return 1.0
    return 1.0


def score_cluster(insiders: list[dict], aggregate_usd: float) -> dict:
    base = 25
    distinct = len({i["name"] for i in insiders})
    insider_score = min(distinct * 5, 25)
    has_ceo = any("CEO" in i["role"] for i in insiders)
    has_cfo = any("CFO" in i["role"] for i in insiders)
    ceo_cfo_bonus = 10 if has_ceo and has_cfo else 0

    if aggregate_usd >= 5_000_000:
        dollar_score = 20
    elif aggregate_usd >= 1_000_000:
        dollar_score = 15
    elif aggregate_usd >= 250_000:
        dollar_score = 10
    elif aggregate_usd >= 100_000:
        dollar_score = 5
    else:
        dollar_score = 0

    roles = [i["role"] for i in insiders]
    has_officer = any(r in ("CEO", "CFO", "COO", "President", "Officer", "Chairman") for r in roles)
    has_director = any(r == "Director" for r in roles)
    cross_role_bonus = 5 if has_officer and has_director else 0

    score = base + insider_score + dollar_score + ceo_cfo_bonus + cross_role_bonus
    score = max(0, min(100, score))

    if score >= 85:
        tier = "high"
    elif score >= 65:
        tier = "medium"
    elif score >= 45:
        tier = "low"
    else:
        tier = "skip"

    return {
        "score": score,
        "tier": tier,
        "components": {
            "base": base,
            "insider_score": insider_score,
            "dollar_score": dollar_score,
            "ceo_cfo_bonus": ceo_cfo_bonus,
            "cross_role_bonus": cross_role_bonus,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Form 4 insider cluster scanner (Signal B)")
    ap.add_argument("--count", type=int, default=100, help="Atom entries to pull (max 100 per SEC)")
    ap.add_argument("--out", type=Path, default=None, help="output JSON path (default: signals/form4-{date}.json)")
    ap.add_argument("--verbose", "-v", action="store_true", help="print every fetch")
    ap.add_argument("--no-write", action="store_true", help="print to stdout only, do not write file")
    args = ap.parse_args()

    ua = get_user_agent()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = args.out or SIGNALS_DIR / f"form4-{today}.json"

    print(f"Scanning Form 4 latest-filings Atom feed (count={args.count})…", file=sys.stderr)
    atom_url = f"{ATOM_URL}?action=getcurrent&type=4&output=atom&count={args.count}"
    try:
        atom_bytes = sec_get(atom_url, ua)
    except Exception as e:
        print(f"ERROR fetching Atom: {e}", file=sys.stderr)
        return 2

    rows = parse_atom(atom_bytes)
    filings = pair_filings(rows)
    print(f"  paired filings: {len(filings)} (from {len(rows)} entries)", file=sys.stderr)

    candidates = candidate_issuer_clusters(filings)
    print(f"  issuer candidates (>={MIN_INSIDERS} distinct insiders): {len(candidates)}", file=sys.stderr)

    qualifying_clusters = []
    for issuer_cik, fs in candidates.items():
        issuer_name = fs[0]["issuer_name"]
        if args.verbose:
            print(f"\n  → {issuer_name} (CIK {issuer_cik}, {len(fs)} filings)", file=sys.stderr)

        all_insiders = {}
        all_purchases = []
        ticker = ""
        skipped_filings = 0
        for f in fs:
            folder = filing_folder_url(f["index_href"])
            xml_url = resolve_xml_url(folder, ua)
            if not xml_url:
                skipped_filings += 1
                continue
            try:
                xml_bytes = sec_get(xml_url, ua)
            except Exception as e:
                if args.verbose:
                    print(f"    ! fetch failed: {e}", file=sys.stderr)
                skipped_filings += 1
                continue

            parsed = parse_form4_xml(xml_bytes)
            if parsed is None:
                skipped_filings += 1
                continue
            if "_error" in parsed:
                if args.verbose:
                    print(f"    ! {parsed['_error']}", file=sys.stderr)
                skipped_filings += 1
                continue

            if parsed["ticker"]:
                ticker = parsed["ticker"]
            if not parsed["purchases"]:
                continue
            for ins in parsed["insiders"]:
                all_insiders.setdefault(ins["name"], ins)
            for p in parsed["purchases"]:
                all_purchases.append({**p, "insider_name": parsed["insiders"][0]["name"] if parsed["insiders"] else "?"})

        distinct_buyers = len({p["insider_name"] for p in all_purchases})
        aggregate_usd = sum(p["amount_usd"] for p in all_purchases)
        weighted_count = sum(role_weight(all_insiders[name]["role"]) for name in {p["insider_name"] for p in all_purchases} if name in all_insiders)

        passes_cluster = (
            distinct_buyers >= MIN_INSIDERS
            and aggregate_usd >= MIN_DOLLARS
            and weighted_count >= 4.0
        )

        cluster = {
            "issuer_cik": issuer_cik,
            "issuer_name": issuer_name,
            "ticker": ticker,
            "distinct_buyers": distinct_buyers,
            "weighted_count": round(weighted_count, 2),
            "aggregate_amount_usd": round(aggregate_usd, 2),
            "purchases": all_purchases,
            "insiders_seen": list(all_insiders.values()),
            "skipped_filings": skipped_filings,
            "passes_cluster_definition": passes_cluster,
        }
        if passes_cluster:
            score = score_cluster(
                [all_insiders[name] for name in {p["insider_name"] for p in all_purchases} if name in all_insiders],
                aggregate_usd,
            )
            cluster.update(score)
            cluster["signal_source"] = "B"
        qualifying_clusters.append(cluster)

    qualifying_clusters.sort(
        key=lambda c: (c.get("passes_cluster_definition", False), c.get("score", 0), c.get("aggregate_amount_usd", 0)),
        reverse=True,
    )

    result = {
        "scan_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "atom_count": args.count,
        "atom_entries_parsed": len(rows),
        "paired_filings": len(filings),
        "candidate_issuers": len(candidates),
        "qualifying_clusters": sum(1 for c in qualifying_clusters if c.get("passes_cluster_definition")),
        "min_insiders": MIN_INSIDERS,
        "min_dollars": MIN_DOLLARS,
        "min_score_to_trade": MIN_SCORE_TO_TRADE,
        "clusters": qualifying_clusters,
    }

    print()
    print(f"==== Form 4 scan {today} ====")
    print(f"  atom entries:       {len(rows)}")
    print(f"  paired filings:     {len(filings)}")
    print(f"  issuer candidates:  {len(candidates)}")
    print(f"  qualifying:         {result['qualifying_clusters']}")
    print()
    for c in qualifying_clusters:
        flag = "✓" if c.get("passes_cluster_definition") else "·"
        score_str = f"score={c.get('score', '—'):>3} tier={c.get('tier', '—'):<6}" if c.get("passes_cluster_definition") else "did not qualify"
        print(f"  {flag} {c['issuer_name'][:40]:<40} {c['ticker'] or '—':<6} buyers={c['distinct_buyers']} ${c['aggregate_amount_usd']:>12,.0f}  {score_str}")
        if c.get("passes_cluster_definition"):
            for p in c["purchases"][:5]:
                print(f"        - {p['insider_name'][:30]:<30} {p['transaction_date']} {p['shares']:>8.0f} sh @ ${p['price']:.2f}  =  ${p['amount_usd']:>10,.0f}")

    if not args.no_write:
        SIGNALS_DIR.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"\n  → wrote {out_path.relative_to(REPO_ROOT) if out_path.is_relative_to(REPO_ROOT) else out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
