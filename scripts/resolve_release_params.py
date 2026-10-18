#!/usr/bin/env python3
"""
Resolves --year/--month/--release-time for fetch_mts_pdf.py on a `schedule`
trigger (no workflow_dispatch inputs given) by reading the "next_release"
block that fetch_mts_pdf.py stored in data/deficit_latest.json during the
previous month's run (parsed off the "release date for the ... Statement
will be ..." notice on the PDF's last page).

If there is no next_release block, falls back to the month after the stored
record_period with an empty release_time. That happens every year: the
August statement prints "The release date for the September ... Statement is
subject to completion of year-end reporting requirements" instead of a date.
The caller treats an empty release_time as "check once whether the PDF is
out yet" rather than sleeping until an announced time.

Prints GITHUB_OUTPUT-formatted `year=`, `month=`, `release_time=` lines on
stdout. Exits 1 with no stdout output only if there's nothing usable at all
(e.g. first-ever run, or no parseable record_period either).
"""
import json
import sys
from pathlib import Path

CAL_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/deficit_latest.json")
if not path.exists():
    print(f"::warning::{path} not found, nothing to resolve", file=sys.stderr)
    sys.exit(1)

data = json.loads(path.read_text())
nr = data.get("next_release")
if nr:
    print(f"year={nr['report_year']}")
    print(f"month={nr['report_month']}")
    print(f"release_time={nr['release_time']}")
    sys.exit(0)

print(f"::warning::no next_release block in {path}; falling back to the month after record_period", file=sys.stderr)
try:
    month_name, year = (data.get("record_period") or "").split()
    month, year = CAL_MONTH_NAMES.index(month_name.capitalize()), int(year)
except ValueError:
    print(f"::warning::no parseable record_period in {path} either", file=sys.stderr)
    sys.exit(1)

month += 1
if month > 12:
    month, year = 1, year + 1
print(f"year={year}")
print(f"month={month}")
print("release_time=")
