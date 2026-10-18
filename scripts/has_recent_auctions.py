"""Exit 0 if a TreasuryDirect JSON list holds any auction within the last N days, else 1."""
import datetime, json, sys

path, days = sys.argv[1], int(sys.argv[2])
cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
try:
    rows = json.load(open(path))
except Exception as e:
    print(f"could not parse {path}: {e}")
    sys.exit(1)
if not isinstance(rows, list):
    print(f"{path} is not a list")
    sys.exit(1)
dates = sorted((r.get("auctionDate") or "")[:10] for r in rows if isinstance(r, dict))
recent = [d for d in dates if d >= cutoff]
print(f"{len(rows)} records, auctionDate {dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}, {len(recent)} since {cutoff}")
sys.exit(0 if recent else 1)
