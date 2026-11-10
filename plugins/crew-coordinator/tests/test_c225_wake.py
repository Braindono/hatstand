"""cc 0.22.5 (scope A-797e1, curator spec 2026-11-09_cc0225-build-spec.md): role-addressed wake pins (T1-T8), filing warnings, relay refusal count.
T1, T2, T3, T5 and the filing tests fail on 0.22.4; T4 and T6 to T8 are guards on paths that must stay as they are.
Run: python3 -B tests/test_c225_wake.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import importlib.util, json, os, subprocess, tempfile, time, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import D, H, TRIG

RUN = "cse_01Ft3xMWC2ETC3SihY2sLPDU"
HERE = os.path.dirname(os.path.abspath(__file__))
WAKE_PY = os.path.join(os.path.dirname(HERE), "scripts", "wake.py")


def entry(role, trig=TRIG, kind="run_once", prompt=None, **kw):
    return dict({"trigger": trig, "kind": kind, "prompt": prompt if prompt is not None else D.wake_prompt(role)}, **kw)


class W(C.Base):
    def setUp(self):
        super().setUp()
        self.op["doorbell"] = {"nudge_per_agent_hour": 60, "nudge_per_pair_hour": 30}

    def holder(self, role="secretary", host="local_sec"):
        a = self.reg(role, host)
        self.warm(a)
        return a

    def pin(self, **ents):
        self.h.wake_pin_apply("operator", ents)

    def do(self, role="secretary", sender=None, kind="task"):
        r = self.send(sender or self.plain, "role:" + role, kind=kind)
        n = r.get("nudge")
        return n["do"] if isinstance(n, dict) else str(n or "")

    def sync_text(self, aid):
        r = self.call("harness_sync", agent=aid)
        return r.get("text") if isinstance(r, dict) and isinstance(r.get("text"), str) else json.dumps(r, default=str)

    def role_assigned(self):
        return [e for e in self.events("role.assigned")]

    # ---- template and lint
    def test_template_is_the_fixed_text_with_only_the_role_filled_in(self):
        self.assertEqual(D.wake_prompt("secretary"),
                         "Ball wake for role:secretary. Peek at the role's mail (as a role-less helper, never register the role), "
                         "leave one line in the role's mail saying a wake arrived, and stop.")

    def test_wake_py_template_equals_the_doorbell_template(self):
        spec = importlib.util.spec_from_file_location("wake_cli", WAKE_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.PROMPT, D.WAKE_PROMPT)

    # T2
    def test_t2_prompts_with_names_ids_or_forbidden_words_are_refused(self):
        self.holder()
        bad = ["Ball wake for role:secretary. Peek at the role's mail, as Gritty Myrtle.",
               D.wake_prompt("secretary") + " #5126714d",
               D.wake_prompt("secretary") + " Edit wake.json.",
               D.wake_prompt("secretary") + " Install the .plugin.",
               D.wake_prompt("secretary") + " Then re-arm.",
               D.wake_prompt("secretary") + " harness_register role=secretary",
               D.wake_prompt("secretary") + " harness_restore",
               D.wake_prompt("curator"),                                  # another role's text
               ""]
        for p in bad:
            with self.assertRaises(H.HarnessError, msg=p):
                self.pin(secretary=entry("secretary", prompt=p))
            with self.assertRaises(H.HarnessError, msg=p):                # and at request time, before the operator is asked
                self.h.request_approval(self.plain, "wake_pin", {"entries": {"secretary": entry("secretary", prompt=p)}})
        self.assertIsNone(self.h.state().wake_pin)

    # T3
    def test_t3_template_plus_one_extra_sentence_is_refused(self):
        self.holder()
        with self.assertRaises(H.HarnessError):
            self.pin(secretary=entry("secretary", prompt=D.wake_prompt("secretary") + " Also read the digest."))
        self.pin(secretary=entry("secretary", prompt="  " + D.wake_prompt("secretary") + "\n"))       # surrounding whitespace only is fine
        self.assertTrue(self.h.state().wake_pin["entries"]["secretary"]["prompt_sha"])

    def test_pin_records_sha_kind_and_the_holder_and_never_the_prompt_text(self):
        a = self.holder()
        self.pin(secretary=entry("secretary"))
        e = self.h.state().wake_pin["entries"]["secretary"]
        self.assertEqual((e["trigger"], e["kind"], e["holder"]), (TRIG, "run_once", a))
        self.assertNotIn("prompt", e)
        self.assertEqual(len(e["prompt_sha"]), 16)

    def test_a_holder_in_the_request_must_be_the_current_holder(self):
        a = self.holder()
        self.pin(secretary=entry("secretary", holder=a))
        with self.assertRaises(H.HarnessError):
            self.pin(secretary=entry("secretary", holder="deadbeef" * 8))

    def test_wake_pin_card_shows_prompt_trigger_and_the_check_line(self):
        self.holder()
        r = self.h.request_approval(self.plain, "wake_pin", {"entries": {"secretary": entry("secretary", link="https://claude.ai/code/x/abc")}})
        for part in (D.wake_prompt("secretary"), TRIG, "https://claude.ai/code/x/abc", "check this text in the cloud UI before approving", "self-reported"):
            self.assertIn(part, r["note"])

    # T1
    def test_t1_holder_swap_makes_the_pin_stale_and_the_line_leaves_it_out(self):
        old = self.holder("secretary", "local_sec1")
        self.pin(secretary=entry("secretary", kind="recurring"))
        self.assertIn(TRIG, self.do())                                  # the holder at pin time: the line names the trigger
        new = self.holder("secretary", "local_sec2")                    # a new holder (new agent id, new sobriquet)
        self.assertNotEqual(old, new)
        with mock.patch.object(D.time, "time", return_value=time.time() + D.TRIG_WAKE_MIN * 60 + 5):
            line = self.do()
        self.assertNotIn("RemoteTrigger", line)
        self.assertNotIn(TRIG, line)
        for who in (self.h.state().agents[old]["sobriquet"], old[:8]):
            self.assertNotIn(who, D.wake_prompt("secretary"))           # the template carries no instance name
        self.assertIn("wake pin for role:secretary is stale", self.sync_text(new))
        e, state = D.wake_pin_state(self.h.state(), "secretary", self.h)
        self.assertEqual(state, "stale")

    def test_a_repin_by_the_new_holder_makes_the_line_return(self):
        self.holder("secretary", "local_sec1")
        self.pin(secretary=entry("secretary", kind="recurring"))
        self.holder("secretary", "local_sec2")
        self.pin(secretary=entry("secretary", kind="recurring"))
        with mock.patch.object(D.time, "time", return_value=time.time() + D.TRIG_WAKE_MIN * 60 + 5):
            self.assertIn(TRIG, self.do())

    # T5
    def test_t5_spent_run_once_is_omitted_and_a_recurring_pin_stays(self):
        self.holder()
        self.pin(secretary=entry("secretary", kind="run_once"))
        r = self.send(self.plain, "role:secretary")
        mid = r["nudge"]["msg_id"]
        self.assertIn(TRIG, r["nudge"]["do"])
        relay = self.reg(host="local_relay")
        D.record_result(self.h, relay, mid, "woke", "HTTP 200 " + RUN)
        self.assertEqual(D.wake_pin_state(self.h.state(), "secretary", self.h)[1], "spent")
        with mock.patch.object(D.time, "time", return_value=time.time() + D.TRIG_WAKE_MIN * 60 + 5):
            self.assertNotIn("RemoteTrigger", self.do())
        self.assertIn("is spent", self.sync_text(self.holder_of("secretary")))
        # a recurring pin with the same reported fire stays
        self.pin(secretary=entry("secretary", kind="recurring"))
        with mock.patch.object(D.time, "time", return_value=time.time() + D.TRIG_WAKE_MIN * 60 + 5):
            r2 = self.send(self.plain, "role:secretary")
        D.record_result(self.h, relay, r2["nudge"]["msg_id"], "woke", "HTTP 200 " + RUN)
        self.assertEqual(D.wake_pin_state(self.h.state(), "secretary", self.h)[1], "ok")

    def test_a_reported_fire_that_is_not_200_does_not_spend_a_run_once_pin(self):
        self.holder()
        self.pin(secretary=entry("secretary", kind="run_once"))
        mid = self.send(self.plain, "role:secretary")["nudge"]["msg_id"]
        D.record_result(self.h, self.reg(host="local_relay"), mid, "woke", "HTTP 500 " + RUN)
        self.assertEqual(D.wake_pin_state(self.h.state(), "secretary", self.h)[1], "ok")

    def holder_of(self, role):
        return self.h.state().role_holder(role)

    # T4
    def test_t4_a_notice_gets_no_trigger_line_and_no_listagents_wording(self):
        self.holder()
        self.pin(secretary=entry("secretary", kind="recurring"))
        r = self.send(self.plain, "role:secretary", kind="notice")
        self.assertNotIn("RemoteTrigger", str(r.get("nudge") or ""))
        self.assertNotIn("ListAgents", self.do())

    def test_legacy_string_pin_is_refused_at_request_and_at_apply(self):     # 0.23.0 (A-08480 item 3 gap 6): was "still works"
        self.holder()
        with self.assertRaisesRegex(H.HarnessError, "plain trig_ string is no longer accepted"):
            self.h.request_approval(self.plain, "wake_pin", {"entries": {"secretary": TRIG}})
        with self.assertRaisesRegex(H.HarnessError, "plain trig_ string is no longer accepted"):
            self.pin(secretary=TRIG)
        self.assertNotIn(TRIG, self.do())

    # T6
    def test_t6_a_fire_never_changes_role_assigned(self):
        a = self.holder()
        self.pin(secretary=entry("secretary", kind="recurring"))
        before = len(self.role_assigned())
        helper = self.reg(host="local_helper")                           # the woken session: a role-less helper
        self.call("harness_inbox", agent=helper, peek=True)
        self.call("harness_send", agent=helper, to="role:secretary", body="a wake arrived", subject="wake", kind="notice")
        self.assertEqual(len(self.role_assigned()), before)
        self.assertEqual(self.holder_of("secretary"), a)
        self.assertIsNone(self.h.state().agents[helper].get("role"))

    # T7
    def test_t7_a_holder_silent_for_3_7_hours_is_not_taken_over(self):
        a = self.holder()
        self.pin(secretary=entry("secretary", kind="recurring"))
        before = len(self.role_assigned())
        later = time.time() + 3.7 * 3600
        with mock.patch.object(D.time, "time", return_value=later), mock.patch.object(H.time, "time", return_value=later):
            helper = self.reg(host="local_helper2")
            self.call("harness_inbox", agent=helper, peek=True)
            self.sync_text(helper)
            self.send(helper, "role:secretary")
        self.assertEqual(len(self.role_assigned()), before)
        self.assertEqual(self.holder_of("secretary"), a)

    # T8
    def test_t8_a_helpers_events_never_count_as_the_holders_activity(self):
        a = self.holder()
        st0 = self.h.state()
        act0 = self.h.holder_activity(st0, a)
        helper = self.reg(host="local_helper3")
        self.call("harness_inbox", agent=helper, peek=True)
        self.call("harness_send", agent=helper, to="role:secretary", body="wake arrived", subject="wake", kind="notice")
        self.assertEqual(self.holder_of("secretary"), a)
        self.assertEqual(self.h.holder_activity(self.h.state(), a), act0)

    # ---- wake.py
    def run_wake(self, *args, home=None):
        d = home or tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "_harness"), exist_ok=True)       # the live copy lives in <home>/_harness/
        p = os.path.join(d, "_harness", "wake.py")
        if not os.path.exists(p):
            import shutil
            shutil.copy(WAKE_PY, p)
        r = subprocess.run([_sys.executable, "-B", p] + list(args), capture_output=True, text=True)
        return d, r

    def test_wake_py_set_with_prompt_file_applies_the_template_check(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "_harness"))
        good, bad = os.path.join(d, "good.txt"), os.path.join(d, "bad.txt")
        open(good, "w").write(D.wake_prompt("secretary") + "\n")
        open(bad, "w").write(D.wake_prompt("secretary") + " Re-arm yourself.")
        _, r = self.run_wake("set", "secretary", TRIG, "--kind", "run_once", "--prompt-file", good, home=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        w = json.load(open(os.path.join(d, "_harness", "wake.json")))
        self.assertEqual(w["secretary"], {"trigger": TRIG, "kind": "run_once", "prompt": D.wake_prompt("secretary")})
        _, r = self.run_wake("set", "design-system", TRIG, "--kind", "run_once", "--prompt-file", bad, home=d)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("design-system", json.load(open(os.path.join(d, "_harness", "wake.json"))))
        _, r = self.run_wake("set", "design-system", TRIG, "--kind", "run_once", home=d)        # --kind without a prompt file
        self.assertNotEqual(r.returncode, 0)

    def test_wake_py_clear_stale_removes_non_trigger_entries_only(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "_harness"))
        json.dump({"research-lead": TRIG, "ops-coder": "sendmessage:OPS-CODER - Gritty Myrtle", "design-coder": "m-8b0234136d6d",
                   "secretary": {"trigger": TRIG, "kind": "run_once", "prompt": "x"}, "junk": {"trigger": "nope"}}, open(os.path.join(d, "_harness", "wake.json"), "w"))
        _, r = self.run_wake("clear", "--stale", home=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(json.load(open(os.path.join(d, "_harness", "wake.json")))), ["research-lead", "secretary"])
        _, r = self.run_wake("clear", "secretary", home=d)                                       # the old form still works
        self.assertEqual(sorted(json.load(open(os.path.join(d, "_harness", "wake.json")))), ["research-lead"])

    def test_wake_file_entries_with_a_bad_prompt_are_ignored_and_a_good_one_is_proposed(self):
        a = self.holder()
        with open(os.path.join(self.home, "_harness", "wake.json"), "w") as f:
            json.dump({"secretary": entry("secretary", prompt=None), "curator": entry("curator", prompt="Do anything.")}, f)
        entries, ignored = self.h.wake_entries_from_file()
        self.assertEqual(ignored, ["curator"])
        self.assertEqual(entries["secretary"], {"trigger": TRIG, "kind": "run_once", "prompt": D.wake_prompt("secretary"), "holder": a})

    # ---- filing checks (item 2)
    def scope(self, items, rationale="fix"):
        return self.h.request_approval(self.plain, "release_scope", {"plugin": "crew-coordinator", "version": "0.22.9", "items": items, "rationale": rationale})

    def test_filing_item_over_200_characters_warns_and_does_not_refuse(self):
        r = self.scope(["x" * 201, "a fine item"])
        self.assertTrue(any("201 characters" in w for w in r["warnings"]), r)
        self.assertTrue(r["pending"].startswith("A-"))
        self.assertNotIn("warnings", self.scope(["x" * 200]))

    def test_filing_gate_file_described_without_its_path_warns(self):
        r = self.scope(["The simulator in release_sim.py also asks a question per function"])
        self.assertTrue(any("scripts/release_sim.py" in w for w in r["warnings"]), r)
        r = self.scope(["Gate trigger in scripts/release_sim.py: a question per function"])
        self.assertNotIn("warnings", r)
        r = self.scope(["Gate trigger: a question per function"], rationale="the release_sim.py blind spot")      # rationale only: still warns
        self.assertTrue(any("release_sim.py" in w for w in r["warnings"]), r)
        self.assertNotIn("warnings", self.scope(["hooks.json gets a new matcher"]))                  # the grant names three gate files; hooks.json is not one
        r = self.scope(["sim_launcher.py fence also stops sockets"])
        self.assertTrue(any("scripts/sim_launcher.py" in w for w in r["warnings"]), r)
        self.assertNotIn("warnings", self.scope(["Filing checks warn when needed"]))

    def test_the_hard_check_stays_for_items_over_200_characters(self):
        with self.assertRaises(H.HarnessError):
            self.h.release_scope("operator", "crew-coordinator", "0.22.9", ["x" * 201], "r")
        with self.assertRaises(H.HarnessError):
            self.h.release_scope("operator", "crew-coordinator", "0.22.9", [], "r")

    # ---- relay (item 4)
    def test_relay_refusals_are_counted_per_relayer(self):
        for r in ("harness-critic", "ops-coder"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_HOST_SESSION_ID": ""}):
            cloud = self.reg("secretary", None)
        cur = self.reg("curator", "local_cur")
        self.warm(cur)
        a = self.reg("harness-critic", "local_critic")
        self.warm(a)
        mid = self.call("harness_send", agent=cloud, to="role:curator", body="b", subject="s", kind="task")["nudge"]["msg_id"]
        D.record_result(self.h, cloud, mid, "skipped", "no_sendmessage")
        self.call("harness_inbox", agent=a, peek=True)
        D.record_result(self.h, a, mid, "refused_by_app", "app cap")
        o = D.outcomes(self.h.store.read_all())
        self.assertEqual(o["refused_by_app"], 1)
        self.assertEqual(o["refused_by_relayer"], {a: 1})
        with self.assertRaises(H.HarnessError):                           # the 0.22.3 restriction stays: a relayer cannot report skipped
            D.record_result(self.h, a, mid, "skipped", "x")

    # ---- fix round 1 (critic m-df6b89f08dbe)
    def spend(self, reason, relay=False):
        self.holder()
        self.pin(secretary=entry("secretary", kind="run_once"))
        mid = self.send(self.plain, "role:secretary")["nudge"]["msg_id"]
        D.record_result(self.h, self.reg(host="local_relay") if relay else self.plain, mid, "woke", reason)
        return D.wake_pin_state(self.h.state(), "secretary", self.h)[1]

    def test_b1_a_sender_reported_woke_without_a_status_spends_a_run_once_pin(self):
        self.assertEqual(self.spend("RemoteTrigger ran"), "spent")

    def test_b1_the_number_after_http_decides_not_the_first_number(self):
        self.assertEqual(self.spend("woke after 120 s, HTTP 200"), "spent")

    def test_b1_a_sender_status_other_than_200_does_not_spend(self):
        self.assertEqual(self.spend("took 200 ms, HTTP 404"), "ok")

    def test_b1_a_relayer_with_200_evidence_still_spends(self):
        self.assertEqual(self.spend("HTTP 200 " + RUN, relay=True), "spent")

    def test_b2_the_plugin_copy_writes_the_homes_wake_json_and_never_its_own_folder(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "_harness"))
        before = sorted(os.listdir(os.path.dirname(WAKE_PY)))
        r = subprocess.run([_sys.executable, "-B", WAKE_PY, "set", "secretary", TRIG] + self.prompt_args(), capture_output=True, text=True,
                           env=dict(os.environ, HARNESS_HOME=home))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.load(open(os.path.join(home, "_harness", "wake.json"))), {"secretary": entry("secretary", kind="recurring")})
        self.assertEqual(sorted(os.listdir(os.path.dirname(WAKE_PY))), before)       # nothing written beside the plugin script

    def test_b2_the_plugin_copy_with_no_home_refuses_instead_of_writing_beside_itself(self):
        env = {k: v for k, v in os.environ.items() if k != "HARNESS_HOME"}
        env["HOME"] = tempfile.mkdtemp()
        before = sorted(os.listdir(os.path.dirname(WAKE_PY)))
        r = subprocess.run([_sys.executable, "-B", WAKE_PY, "get", "secretary"], capture_output=True, text=True, env=env)
        self.assertEqual(sorted(os.listdir(os.path.dirname(WAKE_PY))), before)

    def test_b1_http_forms_and_the_dolines_status_clause(self):
        for reason, want in (("HTTP/1.1 200 OK", "spent"), ("http=200", "spent"), ("HTTP/1.1 502", "ok"), ("HTTP=404 retry", "ok")):
            with self.subTest(reason=reason):
                self.setUp()
                self.assertEqual(self.spend(reason), want)
        self.setUp()
        self.holder()
        self.pin(secretary=entry("secretary", kind="recurring"))
        self.assertIn('Put "HTTP <status>" of the run in the reason.', self.do())

    def test_b2_running_wake_py_in_place_never_moves_the_code_sha(self):
        import hashlib
        def tree_hash():
            h = hashlib.sha256()
            root = os.path.dirname(os.path.dirname(WAKE_PY))
            for d, ds, fs in sorted(os.walk(root)):
                ds.sort()
                for f in sorted(fs):
                    if f.endswith(".pyc"):
                        continue
                    h.update(os.path.join(d, f).encode())
                    h.update(open(os.path.join(d, f), "rb").read())
            return h.hexdigest()
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "_harness"))
        before = tree_hash()
        for args in (("set", "secretary", TRIG, *self.prompt_args()), ("get", "secretary"), ("clear", "--stale"), ("clear", "secretary")):
            r = subprocess.run([_sys.executable, "-B", WAKE_PY] + list(args), capture_output=True, text=True, env=dict(os.environ, HARNESS_HOME=home))
            self.assertEqual(r.returncode, 0, (args, r.stderr))
        self.assertEqual(tree_hash(), before)

    def prompt_args(self, role="secretary"):
        """0.23.0 (gap 6): wake.py set needs --kind and --prompt-file (the plain trig_ form is refused)."""
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        f.write(D.wake_prompt(role))
        f.close()
        self.addCleanup(os.unlink, f.name)
        return ["--kind", "recurring", "--prompt-file", f.name]

    def test_a_trailing_newline_is_not_a_role_or_a_trigger(self):
        self.holder()
        with self.assertRaises(H.HarnessError):
            self.pin(secretary=entry("secretary", trig=TRIG + "\n"))
        with self.assertRaises(H.HarnessError):
            self.pin(**{"secretary\n": entry("secretary")})
        self.assertIsNone(D.pin_entry(TRIG + "\n"))


if __name__ == "__main__":
    unittest.main()
