#!/usr/bin/env python3
"""Snapshot the two slow Fiscal Data series into small static JSON files.

The dashboard used to call api.fiscaldata.treasury.gov directly from the
browser for the TGA balance and the debt overview. Both are published once
per business day, so a live call on every page load bought nothing — and the
API is slow enough to answer that those cards were the last thing to appear
on the page, sometimes by several seconds.

This runs in CI instead and writes what the cards actually render:
a headline figure plus thirteen monthly points each. Same pattern already
used for the MTS deficit via fetch_mts_pdf.py. index.html reads these first
and falls back to the live API if they're missing or stale, so a failure
here degrades to the old behaviour rather than an empty card.
"""

import json
import re
import sys
from datetime import datetime, timezone

import requests

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
TIMEOUT = 90
MONTHS = 13

# The TGA has lived under more than one account_type label as the Daily
# Treasury Statement has evolved, and Treasury's own dataset notes warn it
# may change again — so this matches the way index.html always has, by
# regex, rather than by an exact string that could silently stop matching.
TGA_PATTERN = re.compile(r"treasury general account", re.I)
CLOSING_PATTERN = re.compile(r"closing", re.I)


def get(url):
    res = requests.get(url, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json().get("data", [])


def first_num(row, keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "null"):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def monthly_points(points, months=MONTHS):
    """Last observation of each month, most recent `months` months.

    Mirrors aggregateMonthly() in index.html: later rows for the same month
    overwrite earlier ones, so feed this oldest-first.
    """
    by_month = {}
    for d, v in points:
        by_month[d[:7]] = {"d": d, "v": v}
    keys = sorted(by_month)[-months:]
    return [by_month[k] for k in keys]


def build_tga():
    rows = get(
        f"{BASE}/v1/accounting/dts/operating_cash_balance"
        "?fields=record_date,account_type,open_today_bal,close_today_bal"
        "&sort=-record_date&page[size]=1600"
    )
    tga = [r for r in rows if TGA_PATTERN.search(r.get("account_type") or "")]
    if not tga:
        raise SystemExit("No TGA rows found — refusing to write a snapshot.")

    # Each date carries BOTH a "...(TGA) Opening Balance" row and a
    # "...(TGA) Closing Balance" row, and the regex above matches both. Which
    # one the API happens to return first for a given date is arbitrary, so
    # without this the headline could silently be the opening balance on one
    # day and the closing balance the next. Treasury's dataset notes also
    # record that close_today_bal has been null since 18 Apr 2022 and that
    # the real closing figure now sits in the opening-balance column of the
    # "Closing Balance" row — which is why first_num() falls back the way it
    # does. Prefer the closing rows; fall back to whatever TGA rows exist if
    # the label changes again.
    closing = [r for r in tga if CLOSING_PATTERN.search(r.get("account_type") or "")]
    if closing:
        tga = closing
    else:
        print("WARNING: no TGA closing-balance rows matched; using all TGA rows.",
              file=sys.stderr)

    latest = tga[0]
    bal = first_num(latest, ["close_today_bal", "open_today_bal"])
    if bal is None:
        raise SystemExit("Latest TGA balance is null — refusing to write.")

    series = []
    for r in reversed(tga):  # oldest first
        v = first_num(r, ["close_today_bal", "open_today_bal"])
        if v is not None:
            series.append((r["record_date"], v))

    return {
        "record_date": latest["record_date"],
        "balance_millions": bal,
        "monthly_millions": monthly_points(series),
    }


def build_debt():
    rows = get(
        f"{BASE}/v2/accounting/od/debt_to_penny"
        "?fields=record_date,tot_pub_debt_out_amt,debt_held_public_amt,intragov_hold_amt"
        "&sort=-record_date&page[size]=400"
    )
    if not rows:
        raise SystemExit("No debt_to_penny rows found — refusing to write.")

    latest = rows[0]
    total = first_num(latest, ["tot_pub_debt_out_amt"])
    if total is None:
        raise SystemExit("Latest total public debt is null — refusing to write.")

    # Smoothed daily change over the same trailing window index.html used,
    # so the growth-rate cards keep reading exactly as they did before.
    window = min(90, len(rows) - 1)
    avg_daily = None
    if window > 0:
        then = first_num(rows[window], ["tot_pub_debt_out_amt"])
        if then is not None:
            avg_daily = (total - then) / window

    series = []
    for r in reversed(rows):
        v = first_num(r, ["tot_pub_debt_out_amt"])
        if v is not None:
            series.append((r["record_date"], v))

    return {
        "record_date": latest["record_date"],
        "total_debt": total,
        "debt_held_public": first_num(latest, ["debt_held_public_amt"]),
        "intragov_holdings": first_num(latest, ["intragov_hold_amt"]),
        "avg_daily_change": avg_daily,
        "avg_daily_window_days": window,
        "monthly": monthly_points(series),
    }


def main():
    stamp = datetime.now(timezone.utc).isoformat()
    failures = []

    for name, builder, path in (
        ("TGA", build_tga, "data/tga_latest.json"),
        ("debt", build_debt, "data/debt_latest.json"),
    ):
        try:
            payload = builder()
        except Exception as exc:  # noqa: BLE001 - one series failing must not block the other
            failures.append(f"{name}: {exc}")
            print(f"{name} snapshot FAILED: {exc}", file=sys.stderr)
            continue

        payload["fetched_at"] = stamp
        with open(path, "w") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        print(f"{name} snapshot written to {path} ({payload['record_date']}).")

    # Leaving the previous file in place is the right failure mode: index.html
    # treats a stale snapshot as a miss and falls back to the live API.
    if len(failures) == 2:
        raise SystemExit("Both snapshots failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
