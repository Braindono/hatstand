"""cc 0.14.1: Windows lock path with a mocked msvcrt (real test happens later on a PC). Run: python3 -B tests/test_msvcrt_lock.py"""
import os, sys, tempfile, threading, types, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import harness as H


def fake_msvcrt():
    """Fake msvcrt: LK_NBLCK raises OSError while another fd holds the byte lock, like Windows."""
    m = types.ModuleType("msvcrt")
    m.LK_LOCK, m.LK_NBLCK, m.LK_UNLCK = 1, 2, 0
    m.held, m.calls, m._mu = set(), [], threading.Lock()
    def locking(fd, mode, nbytes):
        with m._mu:
            m.calls.append(mode)
            if mode == m.LK_UNLCK:
                m.held.discard(fd)
            elif fd in m.held or m.held:
                raise OSError("locked")
            else:
                m.held.add(fd)
    m.locking = locking
    return m


class MsvcrtLockTests(unittest.TestCase):
    def setUp(self):
        self.saved = (H.fcntl, H.msvcrt)
        self.fake = fake_msvcrt()
        sys.modules["msvcrt"] = self.fake
        H.fcntl, H.msvcrt = None, self.fake     # force the fcntl-missing branch
        self.tmp = tempfile.mkdtemp()
        self.h = H.Harness(os.path.join(self.tmp, "home")) if os.makedirs(os.path.join(self.tmp, "home")) is None else None

    def tearDown(self):
        H.fcntl, H.msvcrt = self.saved
        sys.modules.pop("msvcrt", None)

    def test_acquire_release(self):
        self.assertEqual(self.h.store.LOCK_MODE, "auto")
        self.h.store.append("t.one", "human", {})
        self.assertIn(self.fake.LK_NBLCK, self.fake.calls)
        self.assertIn(self.fake.LK_UNLCK, self.fake.calls)
        self.assertEqual(self.fake.held, set(), "lock must be released")

    def test_released_on_error(self):
        with self.assertRaises(RuntimeError):
            with self.h.store._lock():
                raise RuntimeError("boom")
        self.assertEqual(self.fake.held, set())

    def test_contention_no_deadlock(self):
        n = 50
        def work(tag):
            for i in range(n):
                self.h.store.append("t.w", "human", {"w": tag, "i": i})
        ts = [threading.Thread(target=work, args=(t,)) for t in "ab"]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertFalse(any(t.is_alive() for t in ts), "deadlock")
        evs = [e for e in self.h.store.read_all() if e["type"] == "t.w"]
        self.assertEqual(len(evs), 2 * n)
        seqs = [e["seq"] for e in self.h.store.read_all()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        self.assertEqual(self.fake.held, set())

    def test_timeout_raises(self):
        self.h.store.LOCK_TIMEOUT = 0.1
        with self.h.store._lock():
            t = threading.Thread(target=lambda: None)
            err = []
            def other():
                try:
                    with self.h.store._lock():
                        pass
                except H.HarnessError as e:
                    err.append(e)
            t = threading.Thread(target=other); t.start(); t.join(10)
        self.assertEqual(len(err), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
