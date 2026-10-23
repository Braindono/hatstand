"""cc 0.16.1 item 8: release-scope gate. Run: python3 -B tests/test_cc161_scope_gate.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first (gate switched off in the test HOME)
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
from test_release_gates import _mk

ITEMS = ["State cache", "transcript indexer"]


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.h, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(self.tmp)
        self.on = mock.patch.object(H, "_operator_file", return_value=({}, []))
        self.on.start()
        self.addCleanup(self.on.stop)
        self.accept = self.h.send(self.envoy, "operator", f"ACCEPT sha={self.sha[:12]}")["id"]

    def changelog(self, ver="1.0.0", body="- State cache on by default\n- transcript indexer added\n"):
        open(os.path.join(self.plug, "CHANGELOG.md"), "w").write(f"# Changelog\n\n## {ver} (unreleased)\n{body}\n## 0.9.0\n- old\n")

    def pub(self, **kw):
        return self.h.publish_release(self.plug, pkg=self.pkg, accept=self.accept, **kw)

    def scope(self, ver="1.0.0", items=ITEMS):
        return self.h.release_scope("operator", "dummy", ver, items, "operator approved 2026-10-23", "D-5221b")

    def test_no_scope_record_no_publish(self):
        self.changelog()
        n = len(self.h.store.read_all())
        with self.assertRaisesRegex(H.HarnessError, "no operator-approved release_scope record"):
            self.pub()
        self.assertEqual(len(self.h.store.read_all()), n)

    def test_wrong_version_refused(self):
        self.changelog()
        self.scope(ver="1.0.1")
        with self.assertRaisesRegex(H.HarnessError, "no operator-approved release_scope record for dummy 1.0.0"):
            self.pub()

    def test_changelog_missing_an_item_refused(self):
        self.changelog(body="- State cache on by default\n")
        self.scope()
        with self.assertRaisesRegex(H.HarnessError, "does not name scope item"):
            self.pub()

    def test_changelog_without_section_or_file_refused(self):
        self.scope()
        with self.assertRaisesRegex(H.HarnessError, "no CHANGELOG.md"):
            self.pub()
        self.changelog(ver="2.0.0")
        with self.assertRaisesRegex(H.HarnessError, "no section for 1.0.0"):
            self.pub()

    def test_matching_record_passes(self):
        self.changelog()
        self.scope()
        r = self.pub()
        self.assertEqual((r["name"], r["version"]), ("dummy", "1.0.0"))

    def test_item_found_only_in_the_versions_own_section(self):
        self.changelog(body="- State cache only\n")
        open(os.path.join(self.plug, "CHANGELOG.md"), "a").write("- transcript indexer (belongs to 0.9.0)\n")
        self.scope()
        with self.assertRaisesRegex(H.HarnessError, "does not name scope item"):
            self.pub()

    def test_override_skips_and_is_logged(self):
        r = self.pub(override="operator says so")
        self.assertIn("gate overridden by operator", r.get("warn", []))
        self.assertTrue([e for e in self.h.store.read_all() if e["type"] == "release.gate_override"])

    def test_gate_can_be_switched_off_only_in_operator_json(self):
        with mock.patch.object(H, "_operator_file", return_value=({"release_scope_gate": False}, [])):
            self.pub()

    def test_scope_is_operator_only_and_validated(self):
        with self.assertRaisesRegex(H.HarnessError, "operator-only"):
            self.h.release_scope(self.lead, "dummy", "1.0.0", ITEMS, "r")
        for bad in (dict(plugin="Bad Name"), dict(version="1.0"), dict(items=[]), dict(items=["x"]), dict(rationale=" ")):
            args = dict(plugin="dummy", version="1.0.0", items=ITEMS, rationale="r")
            args.update(bad)
            with self.assertRaises(H.HarnessError):
                self.h.release_scope("operator", **args)

    def test_agent_request_becomes_a_pending_approval_not_a_record(self):
        M.BOUND.update(home=None, id=None)
        r = M.call(self.h, "harness_admin", {"op": "release_scope", "agent": self.lead,
                                             "args": {"plugin": "dummy", "version": "1.0.0", "items": ITEMS, "rationale": "r"}})
        self.assertIn("pending", r)
        self.assertEqual(self.h.state().release_scopes, {})
        rec = self.h._approval_records()[r["pending"]]
        self.h.approve(r["pending"], "cli-tty", rec["args_digest"][:4], True)      # the operator's step (code from the card)
        self.assertIn(("dummy", "1.0.0"), self.h.state().release_scopes)
        self.changelog()
        self.assertEqual(self.pub()["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
