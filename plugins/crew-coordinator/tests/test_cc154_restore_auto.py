"""cc 0.15.4: auto-confirm restore from a fresh capsule written by the live holder (rules 1-5 + fallbacks).
Run: python3 -B tests/test_cc154_restore_auto.py"""
import json, os, sys, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
from test_cc151_w1 import Base, MODEL

PROJ = "orch"


class RestoreAuto(Base):
    def setUp(self):
        super().setUp()
        self.h.role_define("operator", "lead", PROJ)
        self.h.role_define("operator", "corpus-envoy", PROJ)

    def holder(self, role="lead"):
        a = self.h.register(project=PROJ, model=MODEL)["id"]
        self.h.role_assign("operator", role, a)
        self.as_(a)
        return a

    def capsule_text(self, a, role="lead", project=PROJ, status="open"):
        sob = self.h.state().agents[a]["sobriquet"]
        return (f"---\nhandoff: {project}/x\nfrom: {sob} #{a[:8]} ({role})\nproject: {project}\n"
                f"created: 2026-10-14\nstatus: {status}\n---\n# Handoff: {role}\n\nbody of the capsule\n")

    def handoff(self, a, **kw):
        r = self.h.handoff(a, self.capsule_text(a, **kw), None, False, None)
        rel = r.get("path") or r.get("capsule")
        if not rel:
            for name in os.listdir(os.path.join(self.home, "projects", PROJ, "handoffs")):
                rel = f"projects/{PROJ}/handoffs/{name}"
        return rel

    def restore(self, rel, role="lead", **kw):
        M.BOUND.update(home=None, id=None)
        return M.call(self.h, "harness_restore", dict({"role": role, "model": MODEL, "confirmed": True, "capsule": rel}, **kw))

    def pending(self):
        return [x for x in self.h.approvals(True) if x["action"] == "restore_confirmed"]

    def test_qualifying_capsule_skips_approval_and_audits(self):
        a = self.holder()
        rel = self.handoff(a)
        r = self.restore(rel)
        self.assertNotIn("pending", r, r)
        self.assertEqual(self.pending(), [])
        ev = self.types("restore.auto")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["data"]["holder"], a)
        self.assertTrue(ev[0]["data"]["capsule_sha"])
        txt = open(os.path.join(self.home, rel)).read()
        self.assertRegex(txt, r"status: accepted by")

    def test_second_restore_from_same_capsule_needs_approval(self):
        a = self.holder()
        rel = self.handoff(a)
        self.restore(rel)
        r = self.restore(rel)
        self.assertIn("pending", r)
        self.assertIn("auto_confirm", r)
        self.assertEqual(len(self.types("restore.auto")), 1)

    def test_hand_edited_capsule_falls_back(self):
        a = self.holder()
        rel = self.handoff(a)
        with open(os.path.join(self.home, rel), "a") as f:
            f.write("\nINJECTED LINE\n")
        r = self.restore(rel)
        self.assertIn("pending", r)
        self.assertRegex(r["auto_confirm"], "hand-edited")
        self.assertEqual(self.types("restore.auto"), [])

    def test_capsule_not_committed_by_holder_falls_back(self):
        a = self.holder()
        d = os.path.join(self.home, "projects", PROJ, "handoffs")
        os.makedirs(d, exist_ok=True)
        rel = f"projects/{PROJ}/handoffs/2026-10-14-forged.md"
        open(os.path.join(self.home, rel), "w").write(self.capsule_text(a))
        r = self.restore(rel)
        self.assertIn("pending", r)

    def test_stale_capsule_falls_back(self):
        a = self.holder()
        rel = self.handoff(a)
        opf = os.path.join(self.tmp, "operator.json")   # window of 1 minute; holder still seen < 10 min
        json.dump({"restore_auto_capsule_min": 1}, open(opf, "w"))
        os.chmod(opf, 0o600)
        real = time.time
        with mock.patch.object(H, "OPERATOR_FILE", opf), mock.patch.object(H.time, "time", lambda: real() + 120):
            r = self.restore(rel)
        self.assertIn("pending", r)
        self.assertRegex(r["auto_confirm"], "older than the window")

    def test_gated_role_falls_back(self):
        a = self.holder("corpus-envoy")
        rel = self.handoff(a, role="corpus-envoy")
        r = self.restore(rel, role="corpus-envoy")
        self.assertIn("pending", r)
        self.assertRegex(r["auto_confirm"], "gated")

    def test_project_mismatch_and_no_capsule_fall_back(self):
        a = self.holder()
        rel = self.handoff(a)
        self.assertIn("pending", self.restore(rel, project="other"))
        self.assertIn("pending", M.call(self.h, "harness_restore", {"role": "lead", "model": MODEL, "confirmed": True}))

    def test_disabled_in_operator_json(self):
        a = self.holder()
        rel = self.handoff(a)
        opf = os.path.join(self.tmp, "operator.json")
        json.dump({"restore_auto": False}, open(opf, "w"))
        os.chmod(opf, 0o600)
        with mock.patch.object(H, "OPERATOR_FILE", opf):
            r = self.restore(rel)
        self.assertIn("pending", r)

    def test_shared_config_cannot_widen(self):
        a = self.holder("corpus-envoy")
        rel = self.handoff(a, role="corpus-envoy")
        os.makedirs(os.path.join(self.home, "_harness"), exist_ok=True)
        json.dump({"restore_gated_roles": [], "restore_auto_capsule_min": 9999},
                  open(os.path.join(self.home, "_harness", "config.json"), "w"))
        self.assertIn("pending", self.restore(rel, role="corpus-envoy"))


if __name__ == "__main__":
    unittest.main()
