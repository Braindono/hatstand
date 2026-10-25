"""cc 0.17.0 R-057 (D-fffe6 decision 6): release cadence, one release per plugin per operator-set cycle; a hotfix goes
through the operator override. Run: python3 -B tests/test_c170_r057.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
from test_release_gates import _mk


class FakeSt:
    def __init__(self, reg, now=None):
        self.registry, self.now = reg, now or time.time()


class Cadence(unittest.TestCase):
    def setUp(self):
        self.h = H.Harness(os.path.join(tempfile.mkdtemp(), "Exchange"))
        self.op = {}
        p = mock.patch.object(H, "_operator_file", side_effect=lambda: (dict(self.op), []))
        p.start()
        self.addCleanup(p.stop)

    def check(self, last_age_days, retired=False):
        now = time.time()
        reg = {"crew-coordinator": {"version": "0.16.3", "t": now - last_age_days * 86400, "ts": "2026-10-23T20:04:07Z",
                                    **({"retired": True} if retired else {})}}
        return self.h._check_release_cadence(FakeSt(reg, now), "crew-coordinator", "0.17.0")

    def test_off_until_the_operator_sets_a_cycle(self):
        self.assertIsNone(self.check(0.5))
        self.op = {"release_cycle_days": 0}
        self.assertIsNone(self.check(0.5))

    def test_second_release_inside_the_cycle_refused(self):
        self.op = {"release_cycle_days": 7}
        with self.assertRaisesRegex(H.HarnessError, r"release cadence: crew-coordinator 0\.16\.3 .*7-day cycle.*--operator-override"):
            self.check(2)

    def test_outside_the_cycle_allowed(self):
        self.op = {"release_cycle_days": 7}
        self.assertIsNone(self.check(8))

    def test_first_release_and_retired_entries_pass(self):
        self.op = {"release_cycle_days": 7}
        self.assertIsNone(self.h._check_release_cadence(FakeSt({}), "new-plugin", "0.1.0"))
        self.assertIsNone(self.check(1, retired=True))

    def test_bad_value_counts_as_off(self):
        self.op = {"release_cycle_days": "weekly"}
        self.assertIsNone(self.check(1))


class Wired(unittest.TestCase):
    def test_gated_publish_runs_the_cadence_check(self):
        h, envoy, lead, plug, pkg, sha = _mk(tempfile.mkdtemp())
        acc = h.send(envoy, "operator", f"ACCEPT sha={sha[:12]}")["id"]
        with mock.patch.object(H.Harness, "_check_release_cadence", side_effect=H.HarnessError("release cadence: test")):
            with self.assertRaisesRegex(H.HarnessError, "release cadence: test"):
                h.publish_release(plug, pkg=pkg, accept=acc)
        self.assertFalse([e for e in h.store.read_all() if e["type"] == "release.published"])


if __name__ == "__main__":
    unittest.main()
