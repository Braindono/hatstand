"""0.27.0 item 6: harness_admin op=timer, a wrapper over the Hub feed's timer module (scripts/hub_feed_op.py). It runs the vendored timer module. Run: python3 -B tests/test_timer_op.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
_sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import hub_feed_op as T
import mcp_server as M

class TimerOp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "h"); os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.me = self.h.register(project="p", model="claude-sonnet-5-5", session_id="s1")["id"]

    def test_op_is_listed_with_its_args_and_writes_the_feed_file(self):
        self.assertIn("timer", M.ADMIN_OPS); self.assertIn("ends_at", M.ADMIN_ARGS["timer"])
        r = M.admin(self.h, {"op": "timer", "agent": self.me, "args": {"id": "t1", "label": "build", "ends_at": 99, "owner_role": "curator"}})
        self.assertEqual(r["id"], "t1")
        with open(os.path.join(self.home, "_harness", "hub_feed", "timers.json")) as f:
            doc = json.load(f)
        self.assertEqual(doc["t1"]["label"], "build"); self.assertEqual(r["timer"]["label"], "build")

    def test_bad_args_are_plain_errors(self):
        for a in ({}, {"id": ""}, {"id": "t", "ends_at": 1, "extend_by": 2}):
            with self.assertRaises(H.HarnessError): M.admin(self.h, {"op": "timer", "agent": self.me, "args": a})
        with self.assertRaises(H.HarnessError): M.admin(self.h, {"op": "timer", "agent": self.me, "args": {"id": "t", "x": 1}})   # unknown key

    def test_size_caps(self):
        for a in ({"id": "x" * 81, "ends_at": 1}, {"id": "t", "ends_at": 1, "note": "n" * 5000}):
            with self.assertRaises(H.HarnessError): M.admin(self.h, {"op": "timer", "agent": self.me, "args": a})

    def test_the_timer_module_is_the_vendored_one_never_loaded_from_the_ops_tree(self):
        src = open(os.path.join(HERE, "..", "scripts", "hub_feed_op.py")).read()
        for w in ("importlib", "spec_from_file_location", "HARNESS_OPS_ROOT"):
            self.assertNotIn(w, src)
        self.assertEqual(os.path.dirname(os.path.abspath(T._timers.__file__)), os.path.abspath(os.path.join(HERE, "..", "scripts")))

    def test_not_an_operator_enforced_kind(self):
        import harness_event_map as MAP
        self.assertFalse(MAP.enforced("timer.set", "agent", {}))


if __name__ == "__main__":
    unittest.main()
