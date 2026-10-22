"""cc 0.14.0 tests: M2 release gate, M3 P-40, M6 lock fallback. Run: python3 -B tests/test_release_gates.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, json, multiprocessing, os, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import harness as H


def mkzip(pkg, tree):
    import zipfile
    base = os.path.basename(tree)
    with zipfile.ZipFile(pkg, "w") as z:
        for dp, dn, fns in os.walk(tree):
            for fn in fns:
                fp = os.path.join(dp, fn)
                z.write(fp, os.path.join(base, os.path.relpath(fp, tree)))


def _mk(tmp):
    home = os.path.join(tmp, "home"); os.makedirs(home)
    h = H.Harness(home)
    h.role_define("operator", "corpus-envoy", "orch")
    envoy = h.register(project="orch", model="claude-opus-5-5")["id"]
    h.role_assign("operator", "corpus-envoy", envoy)
    lead = h.register(project="skill-curation", model="claude-opus-5-5")["id"]
    plug = os.path.join(tmp, "dummy"); os.makedirs(os.path.join(plug, ".claude-plugin"))
    with open(os.path.join(plug, ".claude-plugin", "plugin.json"), "w") as f:
        json.dump({"name": "dummy", "version": "1.0.0"}, f)
    pkg = os.path.join(tmp, "dummy-1.0.0.plugin")
    mkzip(pkg, plug)   # cc 0.14.1: the package must match the tree (code-vs-package check)
    with open(pkg, "rb") as f:
        return h, envoy, lead, plug, pkg, hashlib.sha256(f.read()).hexdigest()


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.h, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(self.tmp)

    def pub(self, accept=None, **kw):
        return self.h.publish_release(self.plug, pkg=self.pkg, accept=accept, **kw)

    def msg(self, frm, body):
        return self.h.send(frm, "operator", body)["id"]

    def assertRefused(self, accept=None):
        n = len(self.h.store.read_all())
        with self.assertRaises(H.HarnessError):
            self.pub(accept)
        self.assertEqual(len(self.h.store.read_all()), n, "refused publish must write nothing")

    def test_no_accept(self):
        self.assertRefused(None)

    def test_wrong_sha(self):
        self.assertRefused(self.msg(self.envoy, "ACCEPT deadbeef"))

    def test_not_from_envoy(self):
        self.assertRefused(self.msg(self.lead, f"ACCEPT sha={self.sha[:12]}"))

    def test_accept_older_than_reject(self):
        a = self.msg(self.envoy, f"ACCEPT sha={self.sha[:12]}")
        self.msg(self.envoy, f"REJECT {self.sha[:8]} regression")
        self.assertRefused(a)

    def test_valid(self):
        self.msg(self.envoy, f"REJECT {self.sha[:8]} first try")
        a = self.msg(self.envoy, f"ACCEPT sha={self.sha[:12]} ok")
        out = self.pub(a)
        self.assertEqual(out["accept"], a)
        self.assertNotIn("warn", out)

    def test_override_logged(self):
        out = self.pub(None, override="operator says ship")
        self.assertIn("gate overridden by operator", out["warn"])
        self.assertTrue(any(e["type"] == "release.gate_override" for e in self.h.store.read_all()))

    def test_override_actor_is_caller(self):
        self.pub(None, override="agent says ship", by=self.lead)
        ev = [e for e in self.h.store.read_all() if e["type"] == "release.gate_override"][-1]
        self.assertEqual(ev["actor"], self.lead)
        self.assertEqual(ev["data"]["reason"], "agent says ship")

    def test_override_unresolvable_caller_is_error(self):   # cc 0.15.1 (P2): was "defaults human"; now an error, nothing written
        n = len(self.h.store.read_all())
        with self.assertRaises(H.HarnessError):
            self.pub(None, override="r1", by="no-such-agent")
        self.assertEqual(len(self.h.store.read_all()), n)

    def test_published_actor_is_caller(self):
        a = self.msg(self.envoy, f"ACCEPT sha={self.sha[:12]}")
        self.pub(a, by=self.lead)
        ev = [e for e in self.h.store.read_all() if e["type"] == "release.published"][-1]
        self.assertEqual(ev["actor"], self.lead)

    def test_published_actor_defaults_human(self):
        a = self.msg(self.envoy, f"ACCEPT sha={self.sha[:12]}")
        self.pub(a)
        ev = [e for e in self.h.store.read_all() if e["type"] == "release.published"][-1]
        self.assertEqual(ev["actor"], "human")


class P40Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        home = os.path.join(self.tmp, "home"); os.makedirs(home)
        self.h = H.Harness(home)
        self.haiku = self.h.register(project="p", model="claude-haiku-4-5")["id"]
        self.sonnet = self.h.register(project="p", model="claude-sonnet-5-5")["id"]

    def test_haiku_three_files_blocked(self):
        n = len(self.h.store.read_all())
        with self.assertRaises(H.HarnessError) as c:
            self.h.claim(self.haiku, ["a.md", "b.md", "c.md"])
        self.assertIn("P-40", str(c.exception))
        self.assertEqual(len(self.h.store.read_all()), n)

    def test_haiku_two_files_ok(self):
        r = self.h.claim(self.haiku, ["a.md", "b.md"])
        self.assertTrue(all(x["granted"] for x in r["claims"]))

    def test_sonnet_three_files_ok(self):
        r = self.h.claim(self.sonnet, ["a.md", "b.md", "c.md"])
        self.assertEqual(len(r["claims"]), 3)


def _worker(args):
    home, mode, n, tag = args
    st = H.FileStore(home)
    st.LOCK_MODE = mode
    for i in range(n):
        st.append("test.event", "human", {"w": tag, "i": i})


class LockTests(unittest.TestCase):
    def _run(self, mode):
        tmp = tempfile.mkdtemp()
        H.FileStore(tmp)
        ctx = multiprocessing.get_context("fork")
        ps = [ctx.Process(target=_worker, args=((tmp, mode, 1000, t),)) for t in ("a", "b")]
        [p.start() for p in ps]; [p.join(300) for p in ps]
        self.assertEqual([p.exitcode for p in ps], [0, 0])
        h = H.Harness(tmp)
        evs = [e for e in h.store.read_all() if e["type"] == "test.event"]
        self.assertEqual(len(evs), 2000)
        v = h.verify()
        self.assertTrue(v["ok"], v["problems"])
        seqs = [e["seq"] for e in h.store.read_all()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)), "gap or duplicate")
        for t in ("a", "b"):
            self.assertEqual([e["data"]["i"] for e in evs if e["data"]["w"] == t], list(range(1000)))
        self.assertFalse(os.path.exists(os.path.join(tmp, "_harness", "events.lock.x")))

    def test_excl_fallback_2x1000(self):
        self._run("excl")

    def test_auto_2x1000(self):
        self._run("auto")


if __name__ == "__main__":
    unittest.main(verbosity=2)
