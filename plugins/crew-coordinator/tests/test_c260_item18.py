"""cc 0.26.0 item 18: publish --hotfix RD-<id> waives only the cadence check, and only for a current S1 or S2 release defect of that plugin.
Run: python3 -B tests/test_c260_item18.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
from test_release_gates import _mk


class FakeSt:
    def __init__(self, reg, defects, now=None, used=None):
        self.registry, self.defects, self.now, self.hotfix_used = reg, defects, now or time.time(), used or {}


class Hotfix(unittest.TestCase):
    def setUp(self):
        self.h = H.Harness(os.path.join(tempfile.mkdtemp(), "Exchange"))
        p = mock.patch.object(H, "_operator_file", side_effect=lambda: ({"release_cycle_days": 7}, []))
        p.start()
        self.addCleanup(p.stop)
        self.now = time.time()
        self.reg = {"crew-coordinator": {"version": "0.25.0", "t": self.now - 2 * 86400, "ts": "2026-11-11T00:00:00Z"}}

    def check(self, defects, hotfix="RD-aaaaa", name="crew-coordinator", used=None):
        return self.h._check_release_cadence(FakeSt(self.reg, defects, self.now, used), name, "0.25.1", hotfix=hotfix)

    def d(self, **kw):
        return {"RD-aaaaa": dict({"plugin": "crew-coordinator", "version": "0.25.0", "severity": "S1", "superseded_by": None}, **kw)}

    def test_an_s1_or_s2_defect_of_the_plugin_waives_the_cadence_check(self):
        for sev in ("S1", "S2"):
            self.assertTrue(self.check(self.d(severity=sev)), sev)

    def test_without_the_flag_the_cadence_check_still_bites_and_names_the_flag(self):
        with self.assertRaisesRegex(H.HarnessError, r"release cadence: .*--hotfix RD-<id>.*--operator-override"):
            self.h._check_release_cadence(FakeSt(self.reg, {}, self.now), "crew-coordinator", "0.25.1")

    def test_a_defect_that_does_not_qualify_is_refused_not_ignored(self):
        for defects, rx in (({}, "not a recorded release defect"),
                            (self.d(severity="S3"), "S1 or S2"),
                            (self.d(severity="S0"), "S1 or S2"),
                            (self.d(severity="withdrawn"), "S1 or S2"),
                            (self.d(superseded_by="RD-bbbbb"), "superseded by RD-bbbbb"),
                            (self.d(plugin="other-plugin"), "not crew-coordinator")):
            with self.subTest(rx=rx), self.assertRaisesRegex(H.HarnessError, rx):
                self.check(defects)
        with self.assertRaisesRegex(H.HarnessError, "not a recorded release defect"):
            self.check(self.d(), hotfix="D-12345")                                   # only RD- ids

    def test_a_defect_of_an_old_version_does_not_justify_this_release(self):      # critic B2
        with self.assertRaisesRegex(H.HarnessError, r"defect of crew-coordinator 0\.24\.0; the published version is 0\.25\.0"):
            self.check(self.d(version="0.24.0"))

    def test_a_defect_that_already_waived_a_cadence_is_refused(self):             # critic B2
        with self.assertRaisesRegex(H.HarnessError, r"already waived the cadence of crew-coordinator 0\.25\.1"):
            self.check(self.d(), used={"RD-aaaaa": "crew-coordinator 0.25.1"})

    def test_a_bad_flag_is_refused_even_when_the_cadence_would_not_have_bitten(self):
        self.reg["crew-coordinator"]["t"] = self.now - 30 * 86400
        with self.assertRaisesRegex(H.HarnessError, "not a recorded release defect"):
            self.check({})
        self.assertIsNone(self.check(self.d()))                                      # outside the cycle: nothing to waive, nothing refused

    def test_publish_release_passes_the_flag_to_the_cadence_check_only(self):
        h, envoy, lead, plug, pkg, sha = _mk(tempfile.mkdtemp())
        acc = h.send(envoy, "operator", f"ACCEPT sha={sha[:12]}")["id"]
        seen = {}

        def fake(self_, st, name, ver, hotfix=None):
            seen["hotfix"] = hotfix
            return True
        with mock.patch.object(H.Harness, "_check_release_cadence", fake), mock.patch.object(H.Harness, "_check_release_scope", return_value=None):
            r = h.publish_release(plug, pkg=pkg, accept=acc, hotfix="RD-aaaaa", dry_run=True)
        self.assertEqual(seen["hotfix"], "RD-aaaaa")
        self.assertIn("cadence waived by RD-aaaaa", str(r))
        with self.assertRaisesRegex(H.HarnessError, "--accept"):                      # the ACCEPT gate still runs with the flag
            h.publish_release(plug, pkg=pkg, hotfix="RD-aaaaa", dry_run=True)

    def test_the_release_event_records_the_defect_and_the_notes_say_so(self):     # critic B2
        h, envoy, lead, plug, pkg, sha = _mk(tempfile.mkdtemp())
        acc = h.send(envoy, "operator", f"ACCEPT sha={sha[:12]}")["id"]
        with mock.patch.object(H.Harness, "_check_release_cadence", return_value=True), mock.patch.object(H.Harness, "_check_release_scope", return_value=None):
            h.publish_release(plug, pkg=pkg, accept=acc, hotfix="RD-aaaaa")
        ev = [e for e in h.store.read_all() if e["type"] == "release.published"][-1]["data"]
        self.assertEqual(ev["hotfix"], "RD-aaaaa")
        self.assertIn("cadence waived by RD-aaaaa", ev["notes"])
        self.assertEqual(h.state().hotfix_used, {"RD-aaaaa": "%s %s" % (ev["name"], ev["version"])})

    def test_the_cli_takes_the_flag(self):
        out = subprocess.run([sys.executable, "-B", os.path.join(HERE, "..", "scripts", "harness.py"), "publish", "--help"],
                             capture_output=True, text=True).stdout
        self.assertIn("--hotfix", out)
        flat = " ".join(out.split())
        self.assertIn("CLI only (no MCP argument)", flat)
        self.assertIn("ignored, with a warning", flat)


if __name__ == "__main__":
    unittest.main()
