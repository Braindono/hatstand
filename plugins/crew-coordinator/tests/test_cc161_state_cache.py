"""cc 0.16.1 group 4 (P8): incremental State equals a full rebuild. Run: python3 -B tests/test_cc161_state_cache.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"


def snap(st):
    return json.dumps({k: getattr(st, k) for k in ("agents", "messages", "order", "threads", "tasks", "leases", "roles",
                                                     "roster_seqs", "last_seq", "last_hash", "corpus_count")},
                      sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o))


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)

    def full(self):
        return H.State(self.h.store.read_all())

    def test_equals_full_rebuild_after_every_kind_of_append(self):
        a = self.h.register(project="p", model=MODEL)["id"]
        self.assertEqual(snap(self.h.state()), snap(self.full()))
        b = self.h.register(project="p", model=MODEL)["id"]
        self.h.role_define("operator", "r", "p")
        self.h.send(a, b, "hi", subject="s")
        self.h.inbox(b)
        self.h.claim(a, "x/y.txt")
        for _ in range(3):
            self.assertEqual(snap(self.h.state()), snap(self.full()))
            self.h.send(b, a, "again", subject="s2")

    def test_unchanged_ledger_returns_same_object_with_fresh_now(self):
        self.h.register(project="p", model=MODEL)
        s1 = self.h.state()
        t1 = s1.now
        time.sleep(0.01)
        s2 = self.h.state()
        self.assertIs(s1, s2)
        self.assertGreater(s2.now, t1)

    def test_other_process_append_is_picked_up(self):
        a = self.h.register(project="p", model=MODEL)["id"]
        self.h.state()
        other = H.Harness(self.home)                 # a second Harness on the same ledger = another process
        other.register(project="q", model=MODEL)
        self.assertEqual(snap(self.h.state()), snap(self.full()))
        self.assertEqual(len(self.h.state().agents), 2)

    def test_only_new_lines_are_parsed(self):
        self.h.register(project="p", model=MODEL)
        self.h.state()
        self.h.register(project="q", model=MODEL)
        with mock.patch.object(H.FileStore, "read_all", side_effect=AssertionError("full read")), \
                mock.patch.object(H.FileStore, "parse_lines", side_effect=AssertionError("full parse")):
            self.assertEqual(len(self.h.state().agents), 2)

    def test_shrunk_or_replaced_ledger_rebuilds(self):
        self.h.register(project="p", model=MODEL)
        self.h.register(project="q", model=MODEL)
        self.h.state()
        log = self.h.store.log
        lines = open(log).read().splitlines(True)
        os.replace(log, log + ".old")
        open(log, "w").writelines(lines[:1])        # new inode, fewer events
        self.assertEqual(snap(self.h.state()), snap(self.full()))
        self.assertEqual(len(self.h.state().agents), 1)

    def test_hash_chain_break_rebuilds(self):
        self.h.register(project="p", model=MODEL)
        self.h.state()
        with open(self.h.store.log, "a") as f:        # a line that does not chain to the folded head
            f.write(json.dumps({"seq": 99, "type": "agent.synced", "actor": "x", "data": {}, "t": 1.0, "ts": "t",
                                "prev": "bogus", "hash": "h"}) + "\n")
        self.assertEqual(snap(self.h.state()), snap(self.full()))

    def test_torn_tail_waits_then_completes(self):
        self.h.register(project="p", model=MODEL)
        self.h.state()
        with open(self.h.store.log, "a") as f:
            f.write('{"seq": 5, "type": "agent.sync')        # a writer mid-line
        self.assertEqual(len(self.h.state().agents), 1)     # cached state, torn bytes ignored
        os.truncate(self.h.store.log, os.path.getsize(self.h.store.log) - len('{"seq": 5, "type": "agent.sync'))
        self.h.register(project="q", model=MODEL)
        self.assertEqual(snap(self.h.state()), snap(self.full()))

    def test_switch_off(self):
        self.h.register(project="p", model=MODEL)
        with mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"}):
            self.assertIsNot(self.h.state(), self.h.state())

    def test_speed_not_slower_than_full(self):
        for _ in range(40):
            self.h.register(project="p", model=MODEL)
        self.h.state()
        t = time.time()
        for _ in range(50):
            self.h.state()
        cached = time.time() - t
        t = time.time()
        for _ in range(50):
            self.full()
        self.assertLess(cached, time.time() - t)

    def test_verify_stays_uncached_and_catches_an_in_place_edit_state_cannot_see(self):
        """Residual risk (documented): an older byte edited in place plus a well-formed append is not seen by the cached
        state(); verify() always re-reads the whole file, so it reports the broken chain."""
        a = self.h.register(project="p", model=MODEL)["id"]
        self.h.state()
        log = self.h.store.log
        raw = open(log, "rb").read()
        i = raw.index(b"project")                      # an older byte inside the first event
        open(log, "wb").write(raw[:i] + b"projecX" + raw[i + 7:])
        self.h.register(project="q", model=MODEL)      # a normal append after the edit
        self.assertEqual(len(self.h.state().agents), 2)    # the cached fold took only the new line
        self.assertFalse(self.h.verify()["ok"])            # verify re-reads everything and sees the edit
        self.assertTrue(self.h.verify()["problems"])


if __name__ == "__main__":
    unittest.main()
