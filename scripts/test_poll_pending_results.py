"""Run with:  python3 -m unittest scripts/test_poll_pending_results.py -v"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import poll_pending_results as p  # noqa: E402

ET = p.ET


def et(y, m, d, hh, mm, ss=0):
    return dt.datetime(y, m, d, hh, mm, ss, tzinfo=ET)


def row(term, typ, day, close, **kw):
    r = {"securityTerm": term, "securityType": typ, "cusip": term, "auctionDate": day + "T00:00:00",
         "closingTimeCompetitive": close, "bidToCoverRatio": "", "highYield": "",
         "highInvestmentRate": "", "highDiscountRate": ""}
    r.update(kw)
    return r


class PendingTests(unittest.TestCase):
    # Shapes taken from the real 12 Nov 2026 data.
    thirty = row("30-Year", "Bond", "2026-11-12", "01:00 PM")
    wk17 = row("17-Week", "Bill", "2026-11-12", "01:00 PM")
    wk4_done = row("4-Week", "Bill", "2026-11-12", "11:30 AM", bidToCoverRatio="2.94", highInvestmentRate="4.022")
    tenyr_done = row("10-Year", "Note", "2026-11-10", "01:00 PM", bidToCoverRatio="2.46", highYield="5.020")

    def test_missed_window_case(self):
        # 1:02 PM ET, 2 minutes after close: the exact moment the dispatcher had already stopped.
        got = p.pending([self.thirty, self.wk17, self.wk4_done, self.tenyr_done], et(2026, 11, 12, 13, 2))
        self.assertEqual({r["securityTerm"] for r in got}, {"30-Year", "17-Week"})

    def test_watch_starts_before_close(self):
        self.assertEqual(len(p.pending([self.thirty], et(2026, 11, 12, 12, 56))), 1)
        self.assertEqual(len(p.pending([self.thirty], et(2026, 11, 12, 12, 54))), 0)

    def test_resolved_when_result_published(self):
        done = dict(self.thirty, bidToCoverRatio="2.36", highYield="5.441")
        self.assertEqual(p.pending([done], et(2026, 11, 12, 13, 5)), [])

    def test_bill_counts_as_resolved_without_high_yield(self):
        self.assertTrue(p.has_result(self.wk4_done))

    def test_gives_up_after_grace(self):
        self.assertEqual(p.pending([self.thirty], et(2026, 11, 12, 14, 31)), [])
        self.assertEqual(len(p.pending([self.thirty], et(2026, 11, 12, 14, 29))), 1)

    def test_same_auction_in_two_files_counts_once_and_result_wins(self):
        done = dict(self.thirty, bidToCoverRatio="2.36", highYield="5.441")
        self.assertEqual(len(p.pending([self.thirty, dict(self.thirty)], et(2026, 11, 12, 13, 2))), 1)
        self.assertEqual(p.pending([self.thirty, done], et(2026, 11, 12, 13, 2)), [])

    def test_future_and_old_auctions_ignored(self):
        future = row("20-Year", "Bond", "2026-11-18", "01:00 PM")
        old = row("10-Year", "Note", "2026-11-10", "01:00 PM")
        self.assertEqual(p.pending([future, old], et(2026, 11, 12, 13, 2)), [])

    def test_new_field_names_accepted(self):
        r = {"securityTerm": "30-Year", "competitiveAuctionCloseDate": "2026-11-12T00:00:00",
             "competitiveAuctionCloseTime": "01:00 PM", "bidToCoverRatio": ""}
        self.assertEqual(len(p.pending([r], et(2026, 11, 12, 13, 2))), 1)

    def test_bad_rows_are_skipped_not_fatal(self):
        junk = [None, "x", {}, {"auctionDate": "nope", "closingTimeCompetitive": "??"}]
        self.assertEqual(p.pending(junk, et(2026, 11, 12, 13, 2)), [])

    def test_daylight_saving_needs_no_schedule_change(self):
        # 1 PM ET is 18:00 UTC in November (EST) but 17:00 UTC in July (EDT).
        nov = p.close_time(self.thirty).astimezone(dt.timezone.utc)
        jul = p.close_time(row("30-Year", "Bond", "2027-07-15", "01:00 PM")).astimezone(dt.timezone.utc)
        self.assertEqual(nov.hour, 18)
        self.assertEqual(jul.hour, 17)


if __name__ == "__main__":
    unittest.main()
