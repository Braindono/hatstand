"""cc 0.26.0 item 16: harness results record their size per tool name (one result.measured event per tool per batch, never per call).
Run: python3 -B tests/test_c260_item16.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-sonnet-5-5"


class Measure(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL, session_id="s-a")["id"]

    def ev(self):
        return [e["data"] for e in self.h.store.read_all() if e["type"] == "result.measured"]

    def test_counters_flush_once_per_batch_per_tool(self):
        for i in range(H.Harness.MEASURE_EVERY - 1):
            self.h.measure("harness_inbox", 100 + i)
        self.assertEqual(self.ev(), [])                                   # no event per call
        self.h.measure("harness_inbox", 1000)
        e = self.ev()
        self.assertEqual(len(e), 1)
        self.assertEqual((e[0]["tool"], e[0]["calls"], e[0]["max"]), ("harness_inbox", H.Harness.MEASURE_EVERY, 1000))
        self.assertEqual(e[0]["bytes"], sum(100 + i for i in range(H.Harness.MEASURE_EVERY - 1)) + 1000)

    def test_a_slow_tool_flushes_by_time(self):
        self.h.measure("harness_sync", 50, now=1000.0)
        self.h.measure("harness_sync", 70, now=1000.0 + H.Harness.MEASURE_SECONDS + 1)
        self.assertEqual([(e["tool"], e["calls"], e["bytes"]) for e in self.ev()], [("harness_sync", 2, 120)])

    def test_flush_writes_the_pending_counters_and_tools_are_kept_apart(self):
        self.h.measure("harness_sync", 10)
        self.h.measure("harness_send", 20)
        self.h.measure_flush()
        self.assertEqual(sorted((e["tool"], e["bytes"]) for e in self.ev()), [("harness_send", 20), ("harness_sync", 10)])
        self.h.measure_flush()
        self.assertEqual(len(self.ev()), 2)                                # nothing written twice

    def test_the_server_measures_each_tools_call_and_names_admin_ops(self):
        req = [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "harness_inbox", "arguments": {"agent": self.a}}},
               {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "harness_admin", "arguments": {"agent": self.a, "op": "whoami"}}}]
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("\n".join(json.dumps(r) for r in req) + "\n")):
            M.serve_loop(self.h, None, out)
        self.h.measure_flush()
        sizes = {e["tool"]: e for e in self.ev()}
        self.assertEqual(set(sizes), {"harness_inbox", "harness_admin:whoami"})
        replies = [json.loads(l) for l in out.getvalue().splitlines()]
        self.assertEqual(sizes["harness_inbox"]["bytes"], len(replies[0]["result"]["content"][0]["text"].encode("utf-8")))

    def test_a_failing_ledger_never_breaks_a_call(self):
        with mock.patch.object(self.h.store, "append", side_effect=OSError("disk full")):
            for _ in range(H.Harness.MEASURE_EVERY):
                self.h.measure("harness_inbox", 5)                          # never raises


if __name__ == "__main__":
    unittest.main()
