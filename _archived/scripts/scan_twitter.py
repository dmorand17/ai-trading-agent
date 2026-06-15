#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.14"
# dependencies = ["twscrape>=0.14"]
# ///
"""
Twitter/X influencer tweet scanner — Signal C (references/social-signal.md).

Fetches recent tweets from one or more X accounts, extracts cashtag mentions
($TICKER), deduplicates against prior runs via state/twitter-seen.json, and
writes structured output to signals/.

Credentials (set in .env or shell; required on first run):
  TWITTER_USERNAME       your X handle
  TWITTER_PASSWORD       your X password
  TWITTER_EMAIL          your X email address
  TWITTER_EMAIL_PASSWORD your email password (falls back to TWITTER_PASSWORD)

Usage:
  uv run scripts/scan_twitter.py
  uv run scripts/scan_twitter.py --target traderstewie --target anotherhandle
  uv run scripts/scan_twitter.py --limit 60 --no-write --verbose

Target resolution (first match wins):
  1. --target args
  2. twitter-targets.json in repo root

Output:
  stdout: new cashtag-bearing tweets grouped by handle
  signals/twitter-{YYYY-MM-DD}.json: structured output for the SOP agent

Exit codes:
  0  success (zero new tweets is still success)
  1  misconfiguration (missing credentials or targets)
  2  network / API error
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIGNALS_DIR = REPO_ROOT / "signals"
STATE_DIR = REPO_ROOT / "state"
STATE_FILE = STATE_DIR / "twitter-seen.json"
TARGETS_FILE = REPO_ROOT / "twitter-targets.json"
POOL_DB = REPO_ROOT / ".twscrape" / "accounts.db"

CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
MAX_SEEN_IDS = 1000


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_targets(cli_targets: list[str]) -> list[str]:
    if cli_targets:
        return [h.lstrip("@") for h in cli_targets]
    if TARGETS_FILE.exists():
        targets = json.loads(TARGETS_FILE.read_text())
        return [h.lstrip("@") for h in targets]
    print(
        "ERROR: no targets given. Pass --target or create twitter-targets.json.",
        file=sys.stderr,
    )
    sys.exit(1)


def get_credentials() -> tuple[str, str, str, str]:
    username = os.environ.get("TWITTER_USERNAME", "").strip()
    password = os.environ.get("TWITTER_PASSWORD", "").strip()
    email = os.environ.get("TWITTER_EMAIL", "").strip()
    email_password = os.environ.get("TWITTER_EMAIL_PASSWORD", password).strip()
    if not all([username, password, email]):
        print(
            "ERROR: TWITTER_USERNAME, TWITTER_PASSWORD, and TWITTER_EMAIL must be set.\n"
            "Store them in .env or export them in your shell.",
            file=sys.stderr,
        )
        sys.exit(1)
    return username, password, email, email_password


async def ensure_account(
    api, username: str, password: str, email: str, email_password: str, verbose: bool
) -> None:
    accounts = await api.pool.get_all()
    if accounts:
        if verbose:
            print(f"  account pool: {len(accounts)} account(s) loaded", file=sys.stderr)
        return
    if verbose:
        print("  no accounts in pool — adding and logging in…", file=sys.stderr)
    await api.pool.add_account(username, password, email, email_password)
    await api.pool.login_all()
    accounts = await api.pool.get_all()
    if not accounts:
        print("ERROR: login failed. Check your credentials.", file=sys.stderr)
        sys.exit(2)
    print(f"  login successful ({len(accounts)} account(s))", file=sys.stderr)


async def fetch_new_tweets(
    api, handle: str, limit: int, seen_ids: set[str], verbose: bool
) -> list[dict]:
    try:
        user = await api.user_by_login(handle)
    except Exception as e:
        print(f"  ! could not resolve @{handle}: {e}", file=sys.stderr)
        return []

    if user is None:
        print(f"  ! @{handle} not found", file=sys.stderr)
        return []

    if verbose:
        print(f"  @{handle} → user_id={user.id}", file=sys.stderr)

    new_tweets = []
    try:
        async for tweet in api.user_tweets(user.id, limit=limit):
            tweet_id = str(tweet.id)
            if tweet_id in seen_ids:
                if verbose:
                    print(f"    skip (seen): {tweet_id}", file=sys.stderr)
                continue
            cashtags = list(dict.fromkeys(CASHTAG_RE.findall(tweet.rawContent)))
            new_tweets.append({
                "tweet_id": tweet_id,
                "created_at": tweet.date.isoformat(),
                "text": tweet.rawContent,
                "cashtags": cashtags,
                "likes": tweet.likeCount,
                "retweets": tweet.retweetCount,
                "replies": tweet.replyCount,
                "url": tweet.url,
            })
    except Exception as e:
        print(f"  ! error fetching @{handle}: {e}", file=sys.stderr)

    return new_tweets


async def run(args) -> int:
    from twscrape import API

    targets = load_targets(args.target)
    username, password, email, email_password = get_credentials()
    state = load_state()

    POOL_DB.parent.mkdir(exist_ok=True)
    api = API(str(POOL_DB))
    await ensure_account(api, username, password, email, email_password, args.verbose)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result: dict = {
        "scan_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "targets": {},
    }

    for handle in targets:
        handle_state = state.setdefault(handle, {"last_tweet_id": None, "seen_ids": []})
        seen_ids: set[str] = set(handle_state["seen_ids"])

        print(f"\n@{handle}  (prior seen: {len(seen_ids)})", file=sys.stderr)
        new_tweets = await fetch_new_tweets(api, handle, args.limit, seen_ids, args.verbose)

        new_ids = [t["tweet_id"] for t in new_tweets]
        merged = new_ids + [i for i in handle_state["seen_ids"] if i not in set(new_ids)]
        handle_state["seen_ids"] = merged[:MAX_SEEN_IDS]
        if new_ids:
            handle_state["last_tweet_id"] = new_ids[0]

        result["targets"][handle] = {
            "new_tweet_count": len(new_tweets),
            "tweets_with_cashtags": sum(1 for t in new_tweets if t["cashtags"]),
            "tweets": new_tweets,
        }

    save_state(state)

    print()
    for handle, data in result["targets"].items():
        tagged = [t for t in data["tweets"] if t["cashtags"]]
        print(
            f"@{handle} — {data['new_tweet_count']} new  "
            f"({data['tweets_with_cashtags']} with cashtags)"
        )
        for t in tagged:
            tags = " ".join(f"${c}" for c in t["cashtags"])
            snippet = t["text"][:80].replace("\n", " ")
            print(f"  {tags:<20} \"{snippet}\" (likes={t['likes']} rt={t['retweets']})")

    if not args.no_write:
        SIGNALS_DIR.mkdir(exist_ok=True)
        out_path = SIGNALS_DIR / f"twitter-{today}.json"
        out_path.write_text(json.dumps(result, indent=2))
        print(
            f"\n  → wrote {out_path.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Twitter/X cashtag scanner (Signal C)")
    ap.add_argument(
        "--target", action="append", default=[], metavar="HANDLE",
        help="X handle(s) to scrape (repeatable; overrides twitter-targets.json)",
    )
    ap.add_argument("--limit", type=int, default=40, help="max tweets per handle (default 40)")
    ap.add_argument("--no-write", action="store_true", help="stdout only, no signals file written")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
