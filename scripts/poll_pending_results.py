#!/usr/bin/env python3
"""Wait for just-closed Treasury auctions to publish results, then refresh the data.

Why this exists
---------------
TreasuryDirect posts a result a few minutes AFTER the auction closes (observed
13-Nov-2026 era: 30-Year closed 1:00 PM ET, updatedTimestamp 1:04:21 PM; 10-Year
on 10 Nov, 1:03:35 PM; 4-Week/8-Week 11:33-11:34 AM for an 11:30 AM close).
The external per-minute dispatcher stopped at 12:59 PM ET, so both the 10 Nov
and 12 Nov 1 PM results were missed and only turned up whenever GitHub's
unreliable cron happened to run (46 minutes later on 10 Nov, 2 hours on 12 Nov).

This script is state-driven rather than clock-driven: it looks at the auction
rows themselves, and if any auction has closed (or is about to close) and has no
result yet, it polls TreasuryDirect directly every few seconds until the result
appears, then dispatches the normal "Update Treasury Data" workflow once. If
nothing is pending it exits in about a second, so it is cheap to run often.

Usage
-----
  poll_pending_results.py [--max-minutes 20] [--interval 20] [--no-dispatch]
  poll_pending_results.py --check          # one evaluation of the local data, no polling

Environment: GH_TOKEN (the workflow's GITHUB_TOKEN) is used by `gh` to dispatch.
Times use America/New_York, so daylight-saving changes need no schedule edits.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Start watching this long before the scheduled close, so a run that starts a
# little early (or a cron that fires at :57) is already waiting when it closes.
LEAD = dt.timedelta(minutes=5)
# Stop caring this long after the close: an auction with still no result after
# this is cancelled or broken upstream, and looping on it forever helps nobody.
GRACE = dt.timedelta(minutes=90)

# Any one of these being non-empty means TreasuryDirect has published the result.
# (Bills report highInvestmentRate/highDiscountRate with highYield empty, so
# checking highYield alone would wait forever on a bill.)
RESULT_FIELDS = (
    "bidToCoverRatio",
    "highYield",
    "highInvestmentRate",
    "highDiscountRate",
    "highDiscountMargin",
    "highRate",
    "investmentRate",
)

SEARCH_URL = "https://www.treasurydirect.gov/TA_WS/securities/search?format=json&startDate={start}&endDate={end}"
LOCAL_FILES = ("data/results.json", "data/upcoming.json")


def first(row, *names):
    """First non-empty value among field names (handles the Oct 2026 renames)."""
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return None


def close_time(row):
    """Competitive close as an aware ET datetime, or None if the row lacks one."""
    d = first(row, "auctionDate", "competitiveAuctionCloseDate")
    t = first(row, "closingTimeCompetitive", "competitiveAuctionCloseTime")
    if not d or not t:
        return None
    try:
        day = dt.date.fromisoformat(str(d)[:10])
        clock = dt.datetime.strptime(str(t).strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None
    return dt.datetime.combine(day, clock, tzinfo=ET)


def has_result(row):
    return any(str(row.get(f) if row.get(f) is not None else "").strip() for f in RESULT_FIELDS)


def pending(rows, now):
    """Auctions closing within LEAD from now, or closed within GRACE, with no result.

    The same auction can appear in both results.json and upcoming.json (and, in the
    live feed, once), so rows are grouped by CUSIP + auction date and an auction
    counts as resolved if ANY copy of it carries a result.
    """
    groups = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        c = close_time(r)
        if c is None:
            continue
        key = (r.get("cusip"), c)
        row, resolved = groups.get(key, (r, False))
        groups[key] = (row, resolved or has_result(r))
    out = []
    for (_, c), (r, resolved) in groups.items():
        if not resolved and c - LEAD <= now <= c + GRACE:
            out.append(r)
    return sorted(out, key=close_time)


def label(row):
    c = close_time(row)
    when = c.strftime("%Y-%m-%d %I:%M %p ET") if c else "?"
    return f"{row.get('securityTerm', '?')} {row.get('securityType', '')} ({row.get('cusip', '?')}, closes {when})"


def load_local():
    rows = []
    for path in LOCAL_FILES:
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"could not read {path}: {e}")
            continue
        if isinstance(data, list):
            rows.extend(data)
    return rows


def fetch_live(now):
    """Recent auctions straight from TreasuryDirect, or None on any failure."""
    today = now.date()
    url = SEARCH_URL.format(start=(today - dt.timedelta(days=3)).isoformat(),
                            end=(today + dt.timedelta(days=30)).isoformat())
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pvm-debt-monitor-poller"}), timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:  # network blip, 5xx, bad JSON: just try again next tick
        print(f"  live fetch failed: {e}")
        return None
    return data if isinstance(data, list) else None


def dispatch_refresh():
    print("dispatching 'Update Treasury Data' ...")
    r = subprocess.run(["gh", "workflow", "run", "update-data.yml", "--ref", "main"], capture_output=True, text=True)
    print((r.stdout + r.stderr).strip())
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=20)
    ap.add_argument("--interval", type=float, default=20)
    ap.add_argument("--no-dispatch", action="store_true")
    ap.add_argument("--check", action="store_true", help="evaluate local data once and exit")
    args = ap.parse_args()

    now = dt.datetime.now(ET)
    watch = pending(load_local(), now)
    print(f"now {now:%Y-%m-%d %H:%M:%S} ET; {len(watch)} auction(s) awaiting results")
    for r in watch:
        print("  -", label(r))
    if args.check or not watch:
        return 0

    deadline = time.monotonic() + args.max_minutes * 60
    resolved = False
    while True:
        live = fetch_live(dt.datetime.now(ET))
        if live is not None:
            still = pending(live, dt.datetime.now(ET))
            print(f"{dt.datetime.now(ET):%H:%M:%S} ET: {len(still)} still pending")
            if not still:
                resolved = True
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(args.interval)

    if not resolved:
        print("::warning::Timed out waiting for Treasury results; refreshing anyway.")
    if args.no_dispatch:
        return 0
    return 0 if dispatch_refresh() else 1


if __name__ == "__main__":
    sys.exit(main())
