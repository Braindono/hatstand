"""crew-coordinator 0.27.2: the generated matrix test. Every row of the invariant map (specs/2026-11-24_0.27.2-invariant-map.md, tables I1 to I6) is one case here, built from
the ROWS of tests/m0272_i*.py; EXPECTED lists the row ids, and a row id without a case (or a case without a row id) fails test_every_row_id_has_a_case.
Run: python3 -B -m unittest tests.test_0272_matrix   Depends on: tests/m0272_i1.py, m0272_i2.py, m0272_i3.py, m0272_i4.py, m0272_i5_i6.py."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import unittest

import m0272_i1, m0272_i2, m0272_i3, m0272_i4, m0272_i5_i6

EXPECTED = (
    ["I1-01", "I1-02", "I1-03", "I1-04", "I1-05a", "I1-05b", "I1-05c", "I1-05d", "I1-05e", "I1-05f", "I1-05g", "I1-06", "I1-07", "I1-08", "I1-09", "I1-10"]
    + ["I2-%02d" % n for n in range(1, 14)]
    + ["I3-%02d" % n for n in range(1, 8)]
    + ["I4-%02d" % n for n in range(1, 18)]
    + ["I5-01"] + ["I6-%02d" % n for n in range(1, 9)])
ROWS = {}
for _m in (m0272_i1, m0272_i2, m0272_i3, m0272_i4, m0272_i5_i6):
    for _k, _v in _m.ROWS.items():
        assert _k not in ROWS, "row id used twice: " + _k
        ROWS[_k] = _v


class Matrix(unittest.TestCase):
    def test_every_row_id_has_a_case(self):
        self.assertEqual(sorted(ROWS), sorted(EXPECTED))
        self.assertEqual(len(EXPECTED), len(set(EXPECTED)))


def _make(fn):
    def test(self):
        fn(self)
    test.__doc__ = fn.__doc__
    return test


for _id, _fn in ROWS.items():
    setattr(Matrix, "test_row_" + _id.replace("-", "_"), _make(_fn))


if __name__ == "__main__":
    unittest.main()
