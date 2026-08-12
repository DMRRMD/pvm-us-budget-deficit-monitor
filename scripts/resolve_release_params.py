#!/usr/bin/env python3
"""
Resolves --year/--month/--release-time for fetch_mts_pdf.py on a `schedule`
trigger (no workflow_dispatch inputs given) by reading the "next_release"
block that fetch_mts_pdf.py stored in data/deficit_latest.json during the
previous month's run (parsed off the "release date for the ... Statement
will be ..." notice on the PDF's last page).

Prints GITHUB_OUTPUT-formatted `year=`, `month=`, `release_time=` lines on
stdout. Exits 1 with no stdout output if there's nothing usable to fall back
on (e.g. first-ever run, or the previous PDF's notice couldn't be parsed),
so the caller can skip the poll step instead of running with garbage.
"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/deficit_latest.json")
if not path.exists():
    print(f"::warning::{path} not found, nothing to resolve", file=sys.stderr)
    sys.exit(1)

data = json.loads(path.read_text())
nr = data.get("next_release")
if not nr:
    print(f"::warning::no next_release block in {path}", file=sys.stderr)
    sys.exit(1)

print(f"year={nr['report_year']}")
print(f"month={nr['report_month']}")
print(f"release_time={nr['release_time']}")
