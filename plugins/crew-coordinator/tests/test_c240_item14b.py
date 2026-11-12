"""cc 0.24.0 item 14b (scope A-b2950 item 14, change 3b; extra scope approved by the operator 11-10, D-83cb7; curator build spec
v1.3): mirror_behind() and the envoy's standing sync Do-line while a published release has no verified Hatstand push.
Run: python3 -B tests/test_c240_item14b.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, shutil, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-opus-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        ids = {}
        for r in ("envoy", "curator"):
            self.h.role_define("operator", r, "harness-ops")
            ids[r] = self.h.register(project="harness-ops", model=MODEL)["id"]
            self.h.role_assign("operator", r, ids[r])
        self.envoy, self.curator = ids["envoy"], ids["curator"]

    def publish(self, v):
        self.h.store.append("release.published", "human", {"name": "crew-coordinator", "version": v, "code": "c" * 64})

    def synced(self, mode, verified):
        self.h.store.append("hatstand.synced", self.envoy, {"mode": mode, "exit": 0 if verified else 1, "state": "x",
                                                            "commit": None, "marketplace": "m", "pushed": {}, "verified": verified,
                                                            "plugins": {}})


class P5MirrorBehind(Base):
    def test_p5_the_line_until_a_verified_push(self):
        self.assertIsNone(self.h.mirror_behind())                                   # nothing published yet
        self.publish("0.24.0")
        line = self.h.mirror_behind()
        self.assertRegex(line, r"^crew-coordinator 0\.24\.0 published \d{4}-\d\d-\d\d, not mirrored$")
        self.synced("dry", False)
        self.assertEqual(self.h.mirror_behind(), line)                              # a dry run does not mirror
        self.synced("push", False)
        self.assertEqual(self.h.mirror_behind(), line)                              # an unverified push does not either
        self.synced("push", True)
        self.assertIsNone(self.h.mirror_behind())

    def test_p5_a_later_publish_brings_it_back_and_a_marketplace_edit_does_not(self):
        self.publish("0.24.0")
        self.synced("push", True)
        mk = os.path.join(self.home, "_harness", "marketplace", "plugins", "x")
        os.makedirs(mk)
        with open(os.path.join(mk, "notes.md"), "w") as f:
            f.write("edited without a publish\n")
        self.assertIsNone(self.h.mirror_behind())                                   # no sha compare (critic round 1 b)
        self.publish("0.24.1")
        self.assertIn("0.24.1", self.h.mirror_behind())


class P6DoLine(Base):
    def test_p6_the_envoy_sees_it_and_the_curator_does_not(self):
        self.publish("0.24.0")
        t = self.h.sync(self.envoy, do_only=True)["text"]
        self.assertIn("⇅ hatstand: crew-coordinator 0.24.0 published", t)
        self.assertIn("harness_admin op=hatstand_sync (dry run), then push=true", t)
        self.assertNotIn("⇅ hatstand", self.h.sync(self.curator, do_only=True)["text"])
        self.synced("push", True)
        self.assertNotIn("⇅ hatstand", self.h.sync(self.envoy, do_only=True)["text"])

    def test_p6_once_per_sync(self):
        self.publish("0.24.0")
        self.publish("0.24.1")
        t = self.h.sync(self.envoy, do_only=True)["text"]
        self.assertEqual(t.count("⇅ hatstand"), 1)
        self.assertIn("0.24.1", t)


if __name__ == "__main__":
    unittest.main()
