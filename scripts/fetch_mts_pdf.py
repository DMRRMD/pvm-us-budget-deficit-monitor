#!/usr/bin/env python3
"""
fetch_mts_pdf.py

Polls Treasury's Monthly Treasury Statement (MTS) PDF directly — instead of
the Fiscal Data API — to get the latest federal deficit figure with minimal
lag after release.

Why: Treasury publishes the PDF at an ANNOUNCED, FIXED time (e.g. "2:00 p.m.
EST" printed on the last page of every issue). The Fiscal Data REST API
(mts_table_1) is a separate downstream ingestion pipeline that can lag the
PDF release by anywhere from minutes to several hours. This script targets
the PDF directly for speed, and is meant to run as a tight polling loop
starting a minute or two before the announced release time.

Usage:
    python fetch_mts_pdf.py --year 2026 --month 8 --release-time "2026-09-11T14:00:00-05:00"

Output:
    Writes data/deficit_latest.json (path configurable) with:
    {
        "record_period": "August 2026",
        "month_deficit_millions": <float, negative = deficit>,
        "fytd_deficit_millions": <float>,
        "source": "mts_pdf",
        "source_url": "...",
        "fetched_at": "<ISO8601 UTC>",
        "next_release": {
            "report_year": <int>,
            "report_month": <int, 1-12>,
            "release_time": "<ISO8601, as announced in this PDF>"
        } | null
    }

    The "next_release" block, when found, lets a later scheduled run (with
    no manual workflow_dispatch inputs) know exactly what to poll for next
    month — see scripts/resolve_release_params.py.

Exit codes:
    0  success, file written (this also covers the "cron fired too early,
       nothing to do yet" case — see --max-sleep-seconds)
    1  gave up after max attempts without finding the PDF / parsing it
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import requests

try:
    import pdfplumber
except ImportError:
    print("Missing dependency: pip install pdfplumber requests", file=sys.stderr)
    raise

PDF_URL_TEMPLATE = (
    "https://fiscaldata.treasury.gov/static-data/published-reports/mts/"
    "MonthlyTreasuryStatement_{year}{month:02d}.pdf"
)

# Fallback mirror — same file, served from fiscal.treasury.gov in some months.
PDF_URL_FALLBACK_TEMPLATE = (
    "https://www.fiscal.treasury.gov/files/reports-statements/mts/"
    "mts{year}{month:02d}.pdf"
)

MONTH_NAMES = [
    "", "October", "November", "December", "January", "February", "March",
    "April", "May", "June", "July", "August", "September",
]
# Calendar-month names for building the "Month YYYY" label users expect.
CAL_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def build_pdf_urls(year: int, month: int) -> list[str]:
    return [
        PDF_URL_TEMPLATE.format(year=year, month=month),
        PDF_URL_FALLBACK_TEMPLATE.format(year=year, month=month),
    ]


def try_download(url: str, timeout: float = 10.0) -> bytes | None:
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "PVM-USDebtMonitor/1.0 (+https://usbudget.purevaluemetrics.com)"
        })
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    # A real MTS PDF starts with %PDF-. Treasury sometimes returns a 200
    # with an HTML "not found yet" placeholder — guard against that.
    if not resp.content.startswith(b"%PDF"):
        return None
    return resp.content


# Table 2 / Table 3 both carry a line that looks like:
#   "Total Surplus (+) or Deficit (-) -432,308 -1,798,816 ......"
# Columns are: This Month | Fiscal Year to Date | Full FY estimate | ...
DEFICIT_LINE_RE = re.compile(
    r"Total Surplus \(\+\) or Deficit \(-\)\s+"
    r"(-?[\d,]+)\s+"      # this month
    r"(-?[\d,]+)"         # fiscal year to date
)

RECORD_PERIOD_RE = re.compile(
    r"For Fiscal Year \d{4} Through (\w+) (\d{1,2}), (\d{4})"
)

# Printed on the last page of every issue, e.g.:
#   "The release date for the August 2026 Statement will be 2:00 p.m. EST
#    September 11, 2026."
NEXT_RELEASE_RE = re.compile(
    r"release date for the (\w+)\s+(\d{4})\s+Statement\s+will\s+be\s+"
    r"(\d{1,2}):(\d{2})\s*([ap])\.?\s*m\.?\s*(EST|EDT|ET)?\s+"
    r"(\w+)\s+(\d{1,2}),?\s*(\d{4})",
    re.IGNORECASE,
)

# Treasury prints the announced time already adjusted for the applicable
# zone, so this just needs to turn the printed abbreviation into an offset
# — no DST computation required. Bare "ET" (no distinction given) is rare;
# EST is used as the safer default since most MTS releases fall outside DST.
TZ_OFFSETS = {"EST": "-05:00", "EDT": "-04:00", "ET": "-05:00"}


def parse_next_release(pdf) -> dict | None:
    """Find the "next release" notice, typically on the last page or two."""
    for page in reversed(pdf.pages[-3:]):
        text = page.extract_text() or ""
        m = NEXT_RELEASE_RE.search(text)
        if not m:
            continue
        (month_name, year, hour, minute, ampm, tz,
         rel_month_name, rel_day, rel_year) = m.groups()
        try:
            report_month = CAL_MONTH_NAMES.index(month_name.capitalize())
            rel_month = CAL_MONTH_NAMES.index(rel_month_name.capitalize())
        except ValueError:
            continue
        hour = int(hour)
        if ampm.lower() == "p" and hour != 12:
            hour += 12
        elif ampm.lower() == "a" and hour == 12:
            hour = 0
        offset = TZ_OFFSETS.get((tz or "").upper(), "-05:00")
        release_time = (
            f"{int(rel_year):04d}-{rel_month:02d}-{int(rel_day):02d}"
            f"T{hour:02d}:{int(minute):02d}:00{offset}"
        )
        return {
            "report_year": int(year),
            "report_month": report_month,
            "release_time": release_time,
        }
    return None


def parse_deficit(pdf_bytes: bytes) -> dict:
    tmp_path = Path("/tmp/_mts_current.pdf")
    tmp_path.write_bytes(pdf_bytes)

    month_val = None
    fytd_val = None
    record_period = None

    with pdfplumber.open(tmp_path) as pdf:
        for page in pdf.pages[:10]:  # cover page + Table 1/2/3 are early
            text = page.extract_text() or ""

            if record_period is None:
                m = RECORD_PERIOD_RE.search(text)
                if m:
                    month_name, day, year = m.groups()
                    record_period = f"{month_name} {year}"

            if month_val is None:
                m = DEFICIT_LINE_RE.search(text)
                if m:
                    month_val = float(m.group(1).replace(",", ""))
                    fytd_val = float(m.group(2).replace(",", ""))

            if month_val is not None and record_period is not None:
                break

        next_release = parse_next_release(pdf)

    if month_val is None:
        raise ValueError("Could not locate 'Total Surplus (+) or Deficit (-)' line in PDF")

    return {
        "record_period": record_period,
        "month_deficit_millions": month_val,
        "fytd_deficit_millions": fytd_val,
        "next_release": next_release,
    }


def poll_until_available(
    year: int,
    month: int,
    max_attempts: int,
    interval_seconds: float,
) -> bytes:
    urls = build_pdf_urls(year, month)
    for attempt in range(1, max_attempts + 1):
        for url in urls:
            content = try_download(url)
            if content:
                print(f"[attempt {attempt}] found PDF at {url}", file=sys.stderr)
                return content
        print(
            f"[attempt {attempt}/{max_attempts}] not yet available, "
            f"retrying in {interval_seconds}s",
            file=sys.stderr,
        )
        time.sleep(interval_seconds)
    raise TimeoutError(f"PDF not available after {max_attempts} attempts")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True, help="Reporting year, e.g. 2026")
    ap.add_argument("--month", type=int, required=True, help="Reporting month, 1-12")
    ap.add_argument(
        "--release-time",
        type=str,
        default=None,
        help=(
            "ISO8601 announced release time (e.g. 2026-09-11T14:00:00-05:00). "
            "If given, the script sleeps until shortly before this time before "
            "it starts polling, instead of polling immediately."
        ),
    )
    ap.add_argument("--max-attempts", type=int, default=60)
    ap.add_argument("--interval-seconds", type=float, default=10.0)
    ap.add_argument(
        "--pre-poll-seconds",
        type=float,
        default=90.0,
        help="Start polling this many seconds before --release-time.",
    )
    ap.add_argument(
        "--max-sleep-seconds",
        type=float,
        default=900.0,
        help=(
            "If --release-time is more than this many seconds away, exit "
            "immediately (code 0) instead of sleeping. Protects CI jobs with "
            "a fixed timeout from blocking uselessly through the whole job "
            "when a scheduled run fires well before the real release."
        ),
    )
    ap.add_argument(
        "--output",
        type=str,
        default="data/deficit_latest.json",
        help="Where to write the parsed result (relative to repo root).",
    )
    args = ap.parse_args()

    if args.release_time:
        release_dt = dt.datetime.fromisoformat(args.release_time)
        start_polling_at = release_dt - dt.timedelta(seconds=args.pre_poll_seconds)
        now = dt.datetime.now(release_dt.tzinfo)
        wait_seconds = (start_polling_at - now).total_seconds()
        if wait_seconds > args.max_sleep_seconds:
            print(
                f"Release time {release_dt.isoformat()} is {wait_seconds:.0f}s away, "
                f"more than --max-sleep-seconds ({args.max_sleep_seconds:.0f}s). "
                "Nothing to do yet — exiting cleanly so this run doesn't block on a "
                "cron firing that's simply too early.",
                file=sys.stderr,
            )
            return 0
        if wait_seconds > 0:
            print(f"Sleeping {wait_seconds:.0f}s until {start_polling_at.isoformat()}", file=sys.stderr)
            time.sleep(wait_seconds)

    try:
        pdf_bytes = poll_until_available(
            args.year, args.month, args.max_attempts, args.interval_seconds
        )
    except TimeoutError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        parsed = parse_deficit(pdf_bytes)
    except ValueError as e:
        print(f"ERROR parsing PDF: {e}", file=sys.stderr)
        return 1

    out = {
        "record_period": parsed["record_period"] or f"{CAL_MONTH_NAMES[args.month]} {args.year}",
        "month_deficit_millions": parsed["month_deficit_millions"],
        "fytd_deficit_millions": parsed["fytd_deficit_millions"],
        "source": "mts_pdf",
        "source_url": PDF_URL_TEMPLATE.format(year=args.year, month=args.month),
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "next_release": parsed["next_release"],
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))

    print(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
