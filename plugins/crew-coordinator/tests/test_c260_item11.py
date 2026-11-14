"""cc 0.26.0 item 11: harness_admin op=case action=list: read-only, filters severity, status and date; id, severity, status, date, title; no new event type.
Run: python3 -B tests/test_c260_item11.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import time
import unittest

import test_c230_proctor_events as PE
from test_c230_proctor_events import H, MAG


class List(PE.P):
    def lst(self, agent=None, **a):
        return self.ca(agent or self.plain, action="list", **a)["cases"]

    def test_list_returns_the_five_fields_and_filters(self):
        a = self.open("S2")
        b = self.open("S3")
        rows = self.lst()
        self.assertEqual([r["id"] for r in rows], [a, b])
        self.assertEqual(set(rows[0]), {"id", "severity", "status", "date", "title"})
        self.assertEqual((rows[0]["severity"], rows[0]["status"], rows[0]["title"]), ("S2", "open", "s"))
        self.assertEqual(rows[0]["date"], time.strftime("%Y-%m-%d", time.gmtime()))
        self.assertEqual([r["id"] for r in self.lst(severity="S3")], [b])
        self.assertEqual([r["id"] for r in self.lst(status="open")], [a, b])
        self.assertEqual(self.lst(status="closed"), [])
        self.assertEqual(self.lst(date="2001-01-01"), [])
        self.assertEqual(len(self.lst(date=rows[0]["date"])), 2)

    def test_bad_filters_are_refused_and_nothing_is_written(self):
        self.open("S2")
        n = len(self.h.store.read_all())
        for kw in ({"severity": "S9"}, {"status": "pending"}, {"date": "13-11-2026"}):
            with self.assertRaises(H.HarnessError):
                self.lst(**kw)
        self.lst()
        self.assertEqual(len(self.h.store.read_all()), n)                       # read-only: no event written, no new event type

    def test_a_proctor_sees_no_severity_or_status_of_a_case_it_is_blind_to(self):
        x = self.open("S2")
        row = [r for r in self.lst(agent=self.A) if r["id"] == x][0]
        self.assertEqual((row["severity"], row["status"]), (None, None))
        self.assertEqual(self.lst(agent=self.A, severity="S2"), [])


for _n in [n for n in dir(PE.P) if n.startswith("test_")]:
    setattr(List, _n, None)


if __name__ == "__main__":
    unittest.main()
