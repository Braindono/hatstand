"""cc 0.25.0 item 35: the Stop hook reads the transcript once; last_exchange takes the lines already read. Run: python3 -B tests/test_c250_item35.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import builtins, io, json, os, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import H

TWO = "A:\n```bash\na\n```\nB:\n```bash\nb\n```\n"


class Item35(unittest.TestCase):
    def rows(self, text):
        return [json.dumps({"type": "user", "message": {"content": "go"}}),
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})]

    def test_last_exchange_takes_lines_and_opens_nothing(self):
        with mock.patch.object(builtins, "open", side_effect=AssertionError("last_exchange opened a file")):
            self.assertEqual(H.last_exchange(self.rows("hello"))[1], "hello")
        self.assertEqual(H.last_exchange(self.rows("x" * 5000), cap=100)[1], "x" * 100)

    def test_read_tail_reads_the_last_400k_and_a_missing_file_gives_no_lines(self):
        p = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        open(p, "w").write("a\n" * 300000)
        self.assertLessEqual(sum(len(x) + 1 for x in H.read_tail(p)), 400000 + 2)
        self.assertEqual(H.read_tail(p + ".nope"), [])

    def test_one_stop_call_reads_the_transcript_once_and_still_warns_and_records(self):
        home = os.path.join(tempfile.mkdtemp(), "h")
        os.makedirs(os.path.join(home, "_harness"))
        h = H.Harness(home)
        h.role_define("operator", "ops-coder", "harness-ops", carry="none")
        a = h.register(project="harness-ops", model="claude-sonnet-5-5", session_id="s-35", role="ops-coder")["id"]
        h.store.append("session.bound", a, {"session_id": "s-35", "agent": a})
        tp = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        open(tp, "w").write("\n".join(self.rows(TWO)) + "\n")
        reads = []
        real = H.read_tail
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_HOME": home, "HARNESS_STATE_DIR": tempfile.mkdtemp()}), \
                mock.patch.object(H, "_hook_input", return_value={"session_id": "s-35", "transcript_path": tp}), \
                mock.patch.object(H, "read_tail", side_effect=lambda *x, **k: (reads.append(1), real(*x, **k))[1]), redirect_stdout(buf):
            H.hook("stop")
        self.assertEqual(len(reads), 1)                                              # one read for onecmd AND the restore slot
        self.assertIn("one command at a time", buf.getvalue())
        self.assertEqual(len([e for e in H.Harness(home).store.read_all() if e["type"] == "restore.slot"]), 1)


if __name__ == "__main__":
    unittest.main()
