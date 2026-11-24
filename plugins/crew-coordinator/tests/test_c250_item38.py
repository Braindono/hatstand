"""cc 0.25.0 item 38: observe mode has an end/review date (ask_gate gates.json `observe_until`, idcheck config `idcheck_observe_until`); after it
observe mode is silent until renewed; enforce mode is never auto-off; the harness preferences source path exists in the operator's tree layout.
Run: python3 -B tests/test_c250_item38.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import json, os, sys, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import ask_gate as G
import idcheck


class T(unittest.TestCase):
    def cfg(self, section, today, until=None):
        """0.27.2 (I3): the shipped default carries no date (ended); a date comes only from gates.json, as his renewal."""
        import tempfile
        path = None
        if until:
            fd, path = tempfile.mkstemp(suffix=".json")
            with os.fdopen(fd, "w") as f:
                json.dump({section: {"observe_until": until}}, f)
        try:
            with mock.patch.object(G, "config_path", return_value=path), mock.patch.object(G, "warn"), \
                    mock.patch.object(G.dated_switches, "today", return_value=today):
                G.load_config(section)
                return dict(G.CFG)
        finally:
            if path:
                os.unlink(path)

    def test_ask_gate_observe_switches_itself_off_after_observe_until_in_both_sections(self):
        for sec in ("ask_gate", "harness"):
            self.assertEqual(self.cfg(sec, "2026-11-13")["observe_until"], "")              # shipped default: no date
            self.assertFalse(self.cfg(sec, "2026-11-13")["enabled"], sec)                  # empty = ended
            self.assertTrue(self.cfg(sec, "2026-11-13", "2026-11-20")["enabled"], sec)
            self.assertTrue(self.cfg(sec, "2026-11-20", "2026-11-20")["enabled"], sec)
            self.assertFalse(self.cfg(sec, "2026-11-21", "2026-11-20")["enabled"], sec)

    def test_idcheck_expires_after_its_date_and_a_config_date_renews_it(self):
        self.assertTrue(idcheck.expired(today="2026-11-13"))                                 # shipped default: no date = ended
        self.assertFalse(idcheck.expired("2026-11-20", today="2026-11-13"))
        self.assertTrue(idcheck.expired("2026-11-20", today="2026-11-21"))
        self.assertFalse(idcheck.expired("2027-03-01", today="2026-11-21"))

    def test_the_harness_preferences_source_path_names_a_real_file_layout(self):
        paths = [s["path"] for s in G.HARNESS_DEFAULTS["sources"]]
        self.assertIn("Code/harness-ops/projects/orchestration/OPERATOR-PREFERENCES.md", paths)
        self.assertNotIn("Projects/Exchange/projects/orchestration/OPERATOR-PREFERENCES.md", paths)


    def test_ended_once_writes_one_event_per_day_and_a_new_day_writes_again(self):
        import tempfile
        import harness as H
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "_harness"))
        h = H.Harness(home)
        self.assertEqual(os.path.realpath(h.home), os.path.realpath(home))      # never the real ledger
        self.assertTrue(idcheck.ended_once(h, "idcheck", "aid1", "2026-11-20", today="2026-11-21"))
        self.assertFalse(idcheck.ended_once(h, "idcheck", "aid1", "2026-11-20", today="2026-11-21"))
        self.assertTrue(idcheck.ended_once(h, "idcheck", "aid1", "2026-11-20", today="2026-11-22"))
        self.assertTrue(idcheck.ended_once(h, "askgate", "aid1", "2026-11-20", today="2026-11-22"))     # per hook
        with open(os.path.join(home, "_harness", "events.jsonl"), encoding="utf-8") as f:
            ev = [json.loads(l) for l in f if "hook.observe_ended" in l]
        self.assertEqual([(e["data"]["hook"]) for e in ev], ["idcheck", "idcheck", "askgate"])

    def test_both_harness_sources_resolve_and_a_missing_one_is_one_warning_not_a_crash(self):
        import tempfile, io
        root = os.path.join(tempfile.mkdtemp(), "Claude")
        for rel in ("Projects/Exchange/OPERATOR.md", "Code/harness-ops/projects/orchestration/OPERATOR-PREFERENCES.md"):
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            open(os.path.join(root, rel), "w").write("x")
        with mock.patch.dict(os.environ, {"ASK_GATE_ROOTS": root}):
            for s in G.HARNESS_DEFAULTS["sources"]:
                self.assertEqual(len(G.resolve(s["path"])), 1, s["path"])
            err = io.StringIO()
            G.WARNED.discard("Nope/missing.md")
            with mock.patch.object(sys, "stderr", err):
                self.assertEqual(G.resolve("Nope/missing.md"), [])
                self.assertEqual(G.resolve("Nope/missing.md"), [])
            self.assertEqual(err.getvalue().count("source not found, skipped"), 1)


    def test_an_unwritable_marker_writes_no_event_at_all(self):
        """Critic Q-5e36e611: marker first, event only when the marker write succeeded; a failing marker must not repeat the event on every call."""
        import tempfile
        import harness as H
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "_harness"))
        h = H.Harness(home)
        self.assertEqual(os.path.realpath(h.home), os.path.realpath(home))
        os.makedirs(os.path.join(home, "_harness", "observe_ended_idcheck"))     # a directory where the marker file should go: unwritable
        for _ in range(3):
            self.assertFalse(idcheck.ended_once(h, "idcheck", "aid1", "2026-11-20", today="2026-11-21"))
        with open(os.path.join(home, "_harness", "events.jsonl"), encoding="utf-8") as f:
            self.assertEqual(sum(1 for l in f if "hook.observe_ended" in l), 0)


if __name__ == "__main__":
    unittest.main()
