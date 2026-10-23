"""cc 0.16.0 group 2: role rename with aliases (D-85cbc). Old names resolve; history replays under the new names.
Run: python3 -B tests/test_cc160_rename.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M

MODEL = "claude-sonnet-5-5"


class Rename(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)

    def test_cr_maps_old_names_only(self):
        self.assertEqual(H.cr("corpus-envoy"), "envoy")
        self.assertEqual(H.cr("Corpus-Steward"), "steward")
        self.assertEqual(H.cr("skill-curation-lead"), "curator")
        self.assertEqual(H.cr("claude-code"), "ops-coder")
        self.assertEqual(H.cr("secretary"), "secretary")
        self.assertEqual(H.role_names("envoy"), ["envoy", "corpus-envoy"])

    def test_history_with_old_names_replays_as_new(self):
        self.h.role_define("operator", "corpus-envoy", "orchestration")
        a = self.h.register(project="orchestration", model=MODEL)["id"]
        self.h.role_assign("operator", "corpus-envoy", a)
        st = self.h.state()
        self.assertIn("envoy", st.roles)
        self.assertNotIn("corpus-envoy", st.roles)
        self.assertEqual(st.role_of(a), "envoy")
        self.assertEqual(st.role_holder("corpus-envoy"), a)       # old name still finds the holder
        self.assertIn("orchestration/envoy:", self.h.roster()["text"])

    def test_mail_to_old_role_name_reaches_holder(self):
        self.h.role_define("operator", "envoy", "orchestration")
        e = self.h.register(project="orchestration", model=MODEL, role="corpus-envoy")["id"]   # input with the old name
        s = self.h.register(project="orchestration", model=MODEL)["id"]
        r = self.h.send(s, "role:corpus-envoy", "hello", subject="s", kind="notice")
        self.assertEqual(self.h.state().messages[r["id"]]["to"], ["role:envoy"])
        self.assertIn(r["id"], [x for x in self.h._inbox_ids(self.h.state(), e, unread_only=True)])

    def test_old_mail_label_folds_to_new(self):
        self.h.role_define("operator", "envoy", "orchestration")
        e = self.h.register(project="orchestration", model=MODEL, role="envoy")["id"]
        s = self.h.register(project="orchestration", model=MODEL)["id"]
        r = self.h.send(s, "role:envoy", "x", subject="s", kind="notice")
        # a ledger line written before the rename, with the old label, replays under the new one
        import copy
        evs = copy.deepcopy(self.h.store.read_all())
        [x for x in evs if x["type"] == "message.sent"][-1]["data"]["to"] = ["role:corpus-envoy"]
        self.assertEqual(H.State(evs).messages[r["id"]]["to"], ["role:envoy"])

    def test_old_mail_before_the_cutoff_keeps_its_old_label(self):
        import copy
        self.h.role_define("operator", "envoy", "orchestration")
        self.h.register(project="orchestration", model=MODEL, role="envoy")
        s = self.h.register(project="orchestration", model=MODEL)["id"]
        r = self.h.send(s, "role:envoy", "x", subject="s", kind="notice")
        evs = copy.deepcopy(self.h.store.read_all())
        ev = [x for x in evs if x["type"] == "message.sent"][-1]
        ev["data"]["to"] = ["role:corpus-envoy"]
        ev["ts"] = "2026-10-10T00:00:00.000Z"                      # sent long before the rename
        self.assertEqual(H.State(evs).messages[r["id"]]["to"], ["role:corpus-envoy"])
        ev["ts"] = "2026-10-22T08:00:00.000Z"                      # in flight around the rename
        self.assertEqual(H.State(evs).messages[r["id"]]["to"], ["role:envoy"])

    def test_new_holder_does_not_get_history_as_unread(self):
        import copy
        self.h.role_define("operator", "ops-coder", "orchestration")
        a = self.h.register(project="orchestration", model=MODEL, role="ops-coder")["id"]
        s = self.h.register(project="orchestration", model=MODEL)["id"]
        r = self.h.send(s, "role:ops-coder", "old", subject="s", kind="task")
        evs = copy.deepcopy(self.h.store.read_all())
        ev = [x for x in evs if x["type"] == "message.sent"][-1]
        ev["data"]["to"] = ["role:claude-code"]
        ev["ts"] = "2026-10-12T00:00:00.000Z"
        st = H.State(evs)
        self.assertNotIn(r["id"], self.h._inbox_ids(st, a, unread_only=True))

    def test_old_name_refused_after_overlap(self):
        self.h.role_define("operator", "envoy", "orchestration")
        with mock.patch("time.strftime", return_value="2027-01-01"):
            with self.assertRaisesRegex(H.HarnessError, "renamed to 'envoy'"):
                self.h.register(project="orchestration", model=MODEL, role="corpus-envoy")

    def test_state_note_filed_under_old_name_is_found(self):
        self.h.role_define("operator", "envoy", "orchestration")
        a = self.h.register(project="orchestration", model=MODEL, role="envoy")["id"]
        old = self.h.record(a, "context", "old note", "state before the rename", ["role-state:corpus-envoy", "role-state"], tier="role-state")
        d = self.h.restore_digest(self.h.state(), a, "envoy", [])
        self.assertIn("state before the rename", d)

    def test_config_with_old_role_names_is_canonicalised(self):
        cfg = os.path.join(self.home, "_harness", "config.json")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        json.dump({"curation_roles": {"corpus-envoy": ["archive", "pin"], "corpus-steward": ["archive"]}}, open(cfg, "w"))
        cr = H.curation_roles(self.home)
        self.assertEqual(sorted(cr), ["envoy", "steward"])
        self.assertEqual(cr["envoy"], ["archive", "pin"])

    def test_gated_restore_with_old_name_still_needs_approval(self):
        self.h.role_define("operator", "envoy", "orchestration")
        a = self.h.register(project="orchestration", model=MODEL, role="envoy")["id"]
        M.BOUND.update(home=None, id=None)
        r = M.call(self.h, "harness_restore", {"role": "corpus-envoy", "model": MODEL, "confirmed": True})
        self.assertIn("pending", r)     # an old name must not skip the live-holder check

    def test_steward_prompt_both_spellings(self):
        import ctx_hook as C
        self.assertTrue("[scheduled] steward pass".startswith(C.STEWARD))
        self.assertTrue("[scheduled] corpus-steward pass".startswith(C.STEWARD))

    def test_project_aliases_file_has_no_harness_router(self):
        with open(os.path.join(HERE, "..", "data", "project-aliases.json")) as f:
            a = json.load(f)["aliases"]
        self.assertFalse([k for k in a if "router" in k or "router" in str(a[k])])


if __name__ == "__main__":
    unittest.main()
