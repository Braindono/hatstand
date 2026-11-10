"""cc 0.22.0 release gate (spec v3, scope A-76243 items 1-5): the simulator (S, I1-I8, Q), the gate in publish_release (G), the drift
check (D) and the hooks (H1-H3). Each simulator test runs the real simulator on a tiny home, about 3 s each.
Run: python3 -B tests/test_c220_gate.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import harness as H
import release_sim as RS
import release_guard as RG

MODEL = "claude-sonnet-5-5"
LOCAL = "_harness/data/ontology-mapping.json"
BUG_ANCHOR = "            os.makedirs(dst, exist_ok=True)\n            for fn in sorted(keep):"
BUG_CODE = ("            os.makedirs(dst, exist_ok=True)\n"
            "            if sub == 'data':   # planted 0.21.0-class bug: archive every data file the package does not carry\n"
            "                for fn_ in os.listdir(dst):\n"
            "                    if fn_ not in keep and not fn_.startswith('.') and os.path.isfile(os.path.join(dst, fn_)):\n"
            "                        os.makedirs(os.path.join(dst, '_archive'), exist_ok=True)\n"
            "                        os.replace(os.path.join(dst, fn_), os.path.join(dst, '_archive', fn_))\n"
            "            for fn in sorted(keep):")


def make_home(tmp):
    home = os.path.join(tmp, "Exchange")
    os.makedirs(os.path.join(home, "_harness", "data"))
    h = H.Harness(home)
    h.register(project="harness-ops", model=MODEL, task="t")
    with open(os.path.join(home, LOCAL), "w") as f:
        f.write('{"local": true}\n')
    return home, h


def candidate(tmp, name="cand", patch=None):
    dst = os.path.join(tmp, name)
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("__pycache__", "*.release-sim.*"))
    for d_, _, fs in os.walk(dst):
        os.chmod(d_, 0o755)
        for f_ in fs:
            os.chmod(os.path.join(d_, f_), 0o644)
    for rel, (old, new) in (patch or {}).items():
        p = os.path.join(dst, rel)
        with open(p) as f:
            s = f.read()
        assert s.count(old) == 1, (rel, old[:60])
        with open(p, "w") as f:
            f.write(s.replace(old, new))
    return dst


def answer_all(cand):
    qs = RS.questions(RS.INSTALLED, cand)
    with open(os.path.join(cand, RS.QFILE), "w") as f:
        f.write(RS.questions_md(qs, {q["id"]: "checked in the test" for q in qs}))
    return qs


class Sim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.h = make_home(self.tmp)
        self.base = os.path.join(self.tmp, "simtmp")
        os.makedirs(self.base)

    def run_sim(self, cand, **kw):
        return RS.run(cand, self.home, base=self.base, **kw)

    def test_the_build_itself_passes_and_leaves_no_trace(self):
        before = RS.hash_tree(self.home)
        cand = candidate(self.tmp)
        r = self.run_sim(cand)
        self.assertTrue(r["ok"], r["failed"])
        self.assertEqual(r["questions"], 0)
        self.assertEqual(RS.hash_tree(self.home), before)                                # the live home is byte-identical (test 7)
        self.assertEqual([n for n in os.listdir(self.base) if n.startswith(RS.PREFIX)], [])  # scratch removed
        self.assertFalse(os.path.exists(os.path.join(os.environ["HOME"], ".claude", "crew-coordinator", "state", "unread")))

    def test_worked_example_the_0210_mirror_bug_fails_i1(self):                         # acceptance test 1 (synthetic replay)
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_CODE)})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(r["ok"])
        self.assertIn(f"I1 local file archived: {LOCAL}", r["failed"])

    def test_a_candidate_cannot_grade_itself(self):                                     # acceptance test 8 (critic blocker 1)
        cand = candidate(self.tmp, patch={
            "scripts/harness.py": (BUG_ANCHOR, BUG_CODE),
            "scripts/release_sim.py": ('    return 0 if rep.get("ok") else 1\n', '    return 0\n')})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertIn(f"I1 local file archived: {LOCAL}", r["failed"])                  # the installed simulator ran, not the candidate's
        self.assertTrue(any(q["cls"] == "gate" and q["key"] == "scripts/release_sim.py" for q in RS.questions(RS.INSTALLED, cand)))

    def test_questions_block_until_answered(self):                                       # acceptance test 4
        cand = candidate(self.tmp, patch={
            "scripts/harness.py": ('def drift_explain(self, caller, code_sha_, reason):',
                                   'def drift_explain(self, caller, code_sha_, reason):\n        _x = "Do: nothing (sim test)"')})
        r = self.run_sim(cand)
        self.assertFalse(r["ok"])
        self.assertTrue(r["open_questions"] >= 1 and all(x.startswith("Q unanswered") for x in r["failed"]), r["failed"])
        answer_all(cand)
        self.assertTrue(self.run_sim(cand)["ok"])

    def test_a_write_outside_scratch_is_refused(self):                                  # acceptance test 10 (critic blocker 3)
        escape = os.path.join(self.tmp, "escape.txt")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            f"            try:\n                open({escape!r}, 'w').write('x')\n            except PermissionError:\n                pass\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(os.path.exists(escape))                                       # the write is still stopped
        self.assertTrue(any(x.startswith("I6 write outside scratch refused") for x in r["fence_log"]), r)
        self.assertTrue(r["ok"], r["failed"])                                          # D-5f5c9: the fence is log-only, the gate passes

    def test_log_only_fence_but_the_data_checks_still_block(self):                    # operator ruling D-5f5c9
        escape = os.path.join(self.tmp, "escape_lo.txt")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_CODE.replace(
            "            for fn in sorted(keep):",
            f"            try:\n                open({escape!r}, 'w').write('x')\n            except PermissionError:\n                pass\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(r["ok"])
        self.assertIn(f"I1 local file archived: {LOCAL}", r["failed"])               # the 0.21.0 class still blocks
        self.assertFalse(any(x.startswith("I6 ") for x in r["failed"]))               # the fence finding only logs
        self.assertTrue(r["fence_log"])
        self.assertFalse(os.path.exists(escape))

    def test_a_publish_crashed_by_a_refusal_still_blocks(self):
        escape = os.path.join(self.tmp, "escape_cr.txt")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):", f"            open({escape!r}, 'w').write('x')\n            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(r["ok"])                                                       # the release went unverified
        self.assertTrue(any(x.startswith("publish child:") for x in r["failed"]), r["failed"])

    def test_a_ledger_rewrite_fails_i8(self):                                           # acceptance test 9
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            "            _l = os.path.join(self.store.dir, 'events.jsonl'); _b = open(_l, 'rb').read(); open(_l, 'wb').write(_b.replace(b'\"v\":1', b'\"v\":2', 1))\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertTrue(any(x.startswith("I8 ledger rewritten") for x in r["failed"]), r["failed"])
        self.assertTrue(any(x.startswith("I7b") for x in r["failed"]), r["failed"])

    def test_scenario_writes_do_not_fail_i1(self):                                      # critic blocker 2: after-hash before the scenario
        cand = candidate(self.tmp)
        r = self.run_sim(cand)
        self.assertEqual(r["checks"]["I1"], [])
        self.assertEqual(r["checks"]["I8"], [])

    def test_an_added_approval_action_needs_the_scope(self):
        cand = candidate(self.tmp, patch={"scripts/harness.py": ('"case_close")   # 0.23.0 (A-08480 item 2): proctor case approvals',     # 0.23.0: the tuple's end moved
                                                                 '"case_close", "sim_extra")   # 0.23.0 (A-08480 item 2): proctor case approvals')})
        answer_all(cand)
        self.assertIn("I5 approval action added without scope: sim_extra", self.run_sim(cand)["failed"])
        self.assertNotIn("I5 approval action added without scope: sim_extra", self.run_sim(cand, allow_actions=["sim_extra"])["failed"])

    def test_leftovers_are_archived_not_deleted_and_a_live_run_is_left_alone(self):
        old, live = os.path.join(self.base, RS.PREFIX + "killed"), os.path.join(self.base, RS.PREFIX + "live")
        os.makedirs(os.path.join(old, "x"))
        os.makedirs(live)
        os.utime(old, (time.time() - 3 * 3600,) * 2)
        RS.sweep(self.base)
        self.assertTrue(os.path.isdir(os.path.join(self.base, RS.PREFIX + "archive", RS.PREFIX + "killed", "x")))
        self.assertTrue(os.path.isdir(live))                                            # critic S4 non-blocking: a concurrent run

    def test_s4_b4_os_system_and_non_python_subprocesses_are_stopped(self):            # critic S4 blocker 4 (X1b, F5)
        esc = os.path.join(self.tmp, "escape2.txt")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            f"            os.system('/usr/bin/touch {esc}')\n            import subprocess as _sp; _sp.run(['/usr/bin/true'])\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(os.path.exists(esc))
        self.assertTrue(any("os.system" in x for x in r["checks"]["I6"]), r["checks"]["I6"])

    def test_s4r_b1_a_python_grandchild_is_refused(self):                            # critic S4 rerun blocker 1 (X2)
        esc = os.path.join(self.tmp, "escape3.txt")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            "            import subprocess as _sp\n"
            f"            _sp.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x2_helper.py')])\n"
            "            for fn in sorted(keep):"))})
        with open(os.path.join(cand, "scripts", "x2_helper.py"), "w") as f:
            f.write(f"open({esc!r}, 'w').write('x')\n")
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(os.path.exists(esc))
        self.assertTrue(any("subprocess.Popen" in x for x in r["checks"]["I6"]), r["checks"]["I6"])

    def test_s4r_b2_a_database_outside_scratch_is_refused(self):                      # critic S4 rerun blocker 2 (X4)
        esc = os.path.join(self.tmp, "escape4.db")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            f"            import sqlite3 as _q; _c = _q.connect({esc!r}); _c.execute('create table t (x)'); _c.commit()\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(os.path.exists(esc))
        self.assertTrue(any("connect" in x for x in r["checks"]["I6"]), r["checks"]["I6"])

    def test_s4r_b2_low_level_fork_exec_is_stubbed(self):
        esc = os.path.join(self.tmp, "escape5.txt")
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            "            import _posixsubprocess as _px\n"
            f"            _px.fork_exec(['/usr/bin/touch', {esc!r}], [b'/usr/bin/touch'], True, (), None, None, -1, -1, -1, -1, -1, -1, -1, -1, False, False, None, None, None, -1, None)\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertFalse(os.path.exists(esc))
        self.assertTrue(any("fork_exec" in x for x in r["checks"]["I6"]) or r["checks"]["setup"], r["checks"])

    def test_s4r2_a_dir_fd_write_is_refused(self):                                    # critic S4 rerun 2 blocker (X5)
        out_dir = os.path.join(self.tmp, "outside")
        os.makedirs(out_dir)
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            f"            _d = os.open({out_dir!r}, os.O_RDONLY)\n"
            "            os.open('X5-escaped.marker', os.O_CREAT | os.O_WRONLY, dir_fd=_d)\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertEqual(os.listdir(out_dir), [])
        self.assertTrue(any("os.open write" in x for x in r["checks"]["I6"]), r["checks"]["I6"])

    def test_s4r2_a_duplicated_outside_dir_fd_is_refused(self):
        out_dir = os.path.join(self.tmp, "outside2")
        os.makedirs(out_dir)
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            f"            _d = os.dup(os.open({out_dir!r}, os.O_RDONLY))\n"
            "            os.open('x5c.marker', os.O_CREAT | os.O_WRONLY, dir_fd=_d)\n"
            "            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertEqual(os.listdir(out_dir), [])
        self.assertTrue(r["checks"]["I6"], r["checks"])

    def test_s4r2_a_foreign_dir_fd_is_refused(self):
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):",
            "            _fd = open(__file__).fileno()\n            os.mkdir('x5b', dir_fd=_fd)\n            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertTrue(any("dir_fd the fence did not open" in x for x in r["checks"]["I6"]), r["checks"]["I6"])

    def test_s4r_an_unlisted_audit_event_is_refused_by_default(self):                # envoy m-64d4a79dac01: deny by default
        cand = candidate(self.tmp, patch={"scripts/harness.py": (BUG_ANCHOR, BUG_ANCHOR.replace(
            "            for fn in sorted(keep):", "            os.kill(os.getpid(), 0)\n            for fn in sorted(keep):"))})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertTrue(any("unknown audit event os.kill" in x for x in r["checks"]["I6"]), r["checks"]["I6"])

    def test_s4_b1_a_name_at_the_call_site_fails_i3b(self):                            # critic S4 blocker 1 (F3)
        cand = candidate(self.tmp, patch={"scripts/doorbell.py": (
            '"do": " ; ".join(_do_one(x, g, line, mid) for _, _, x, g in ring)}',
            '"do": " ; ".join(_do_one(x, g, line, mid) + " " + str(a.get("sobriquet")) for _, a, x, g in ring)}')})
        answer_all(cand)
        self.assertIn("I3b the Do-line carries a name, a ROLE row or a ListAgents check (role-only addressing, D-3e5e7)",
                      self.run_sim(cand)["failed"])

    def test_s4_b1_a_new_change_in_an_answered_function_gets_a_new_question(self):
        anchor = "parts.append(f'Do: SendMessage to {hid}: {line}"
        c1 = candidate(self.tmp, "c1", patch={"scripts/doorbell.py": (anchor, anchor.replace("{hid}:", "{hid} now:"))})
        c2 = candidate(self.tmp, "c2", patch={"scripts/doorbell.py": (anchor, anchor.replace("{hid}:", "{hid} soon:"))})
        q1 = {q["id"] for q in RS.questions(RS.INSTALLED, c1) if q["cls"] == "doline"}
        q2 = {q["id"] for q in RS.questions(RS.INSTALLED, c2) if q["cls"] == "doline"}
        self.assertTrue(q1 and q2 and not (q1 & q2))

    def test_s4_b2_a_hook_that_drops_the_rpm_path_fails_i9(self):                     # critic S4 blocker 2 (F10)
        cand = candidate(self.tmp, patch={"scripts/release_guard.py": (
            'if "/local-agent-mode-sessions/" in p and "/rpm/" in p:', 'if False:')})
        answer_all(cand)
        r = self.run_sim(cand)
        self.assertIn("I9 hook probe failed: deny_rpm", r["failed"])
        self.assertTrue(any(q["cls"] == "gate" and q["key"] == "scripts/release_guard.py" for q in RS.questions(RS.INSTALLED, cand)))

    def test_s4_b2_a_deleted_do_line_raises_a_question(self):
        old = '". Do: harness_send to role:curator,role:secretary kind=notice "'
        cand = candidate(self.tmp, patch={"scripts/release_guard.py": (old, '". Tell the curator "')})
        self.assertTrue(any(q["cls"] == "doline" and q["key"].startswith("scripts/release_guard.py::post_check#")
                            for q in RS.questions(RS.INSTALLED, cand)))

    def test_the_report_carries_no_do_line_text(self):
        cand = candidate(self.tmp)
        r = self.run_sim(cand)
        self.assertNotIn("Do: SendMessage", json.dumps(r))


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.h = make_home(self.tmp)

    def fake_sim(self, ok=True, failed=()):
        out = json.dumps({"ok": ok, "failed": list(failed), "checks": {"I1": list(failed)}, "questions": 0, "open_questions": 0, "seconds": 1})
        return mock.patch.object(H.subprocess, "run", return_value=mock.Mock(stdout=out + "\n", returncode=0 if ok else 1))

    def test_gate_skips_other_plugins_tests_and_the_sim_child(self):
        st = self.h.state()
        self.assertEqual(self.h._release_gate(ROOT, "dummy", "1.0.0", st, True), (None, None))
        with mock.patch.object(H, "RELEASE_GATE_ENABLED", False):
            self.assertEqual(self.h._release_gate(ROOT, "crew-coordinator", "1.0.0", st, True), (None, None))
        with mock.patch.object(H, "_SIM_CHILD", True):
            self.assertEqual(self.h._release_gate(ROOT, "crew-coordinator", "1.0.0", st, True), (None, None))

    def test_gate_runs_the_installed_simulator_never_the_env_root(self):
        with self.fake_sim() as run, mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent/candidate"}):
            self.h._release_gate(ROOT, "crew-coordinator", "9.9.9", self.h.state(), True)
        self.assertEqual(run.call_args[0][0][3], os.path.join(H.OWN_ROOT, "scripts", "release_sim.py"))

    def test_a_dry_run_writes_nothing_a_real_run_logs_release_sim(self):
        n = len(self.h.store.read_all())
        with self.fake_sim(False, ["I1 local file archived: x"]):
            f, _ = self.h._release_gate(ROOT, "crew-coordinator", "9.9.9", self.h.state(), True)
        self.assertEqual(f, ["I1 local file archived: x"])
        self.assertEqual(len(self.h.store.read_all()), n)
        with self.fake_sim(True):
            self.h._release_gate(ROOT, "crew-coordinator", "9.9.9", self.h.state(), False)
        ev = [e for e in self.h.store.read_all() if e["type"] == "release.sim"]
        self.assertEqual(len(ev), 1)
        self.assertTrue(ev[0]["data"]["ok"])
        self.assertTrue(os.path.isfile(os.path.join(self.home, "_harness", "release_prehash.json")))
        self.assertIn(ev[0]["data"]["code_sha"], self.h.state().sim_pass_codes)

    def test_publish_refuses_on_failure_and_the_override_names_the_checks(self):
        with self.fake_sim(False, ["I1 local file archived: x"]):
            with self.assertRaises(H.HarnessError) as e:
                self.h.publish_release(path=ROOT, build=True, pkg=os.path.join(self.tmp, "p.plugin"))
            self.assertIn("release gate: 1 check(s) failed", str(e.exception))
            self.h.publish_release(path=ROOT, build=True, pkg=os.path.join(self.tmp, "p.plugin"), override="test hotfix")
        ov = [e for e in self.h.store.read_all() if e["type"] == "release.gate_override"]
        self.assertEqual(ov[-1]["data"]["failed"], ["I1 local file archived: x"])

    def test_scope_names_the_allowed_actions(self):
        self.h.store.append("release.scope", "human", {"plugin": "crew-coordinator", "version": "9.9.9",
                                                         "items": ["Approval actions added: sim_extra, other_one"], "rationale": "r"})
        with self.fake_sim() as run:
            self.h._release_gate(ROOT, "crew-coordinator", "9.9.9", self.h.state(), True)
        argv = run.call_args[0][0]
        self.assertEqual(argv[argv.index("--allow-actions") + 1], "other_one,sim_extra")

    def test_scope_names_the_changed_gate_files(self):
        self.h.store.append("release.scope", "human", {"plugin": "crew-coordinator", "version": "9.9.8",
                                                         "items": ["Gate files changed: hooks/hooks.json, scripts/harness.py::publish_release"], "rationale": "r"})
        with self.fake_sim() as run:
            self.h._release_gate(ROOT, "crew-coordinator", "9.9.8", self.h.state(), True)
        argv = run.call_args[0][0]
        self.assertEqual(argv[argv.index("--gate-files") + 1], "hooks/hooks.json,scripts/harness.py::publish_release")


class Drift(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.h = make_home(self.tmp)
        self.own = H.code_sha(H.OWN_ROOT, "plugin")

    def publish_event(self, code):
        self.h.store.append("release.published", "human", {"name": "crew-coordinator", "version": "0.21.2", "code": code, "kind": "plugin"})

    def drifts(self):
        return [e for e in self.h.store.read_all() if e["type"] == "release.drift"]

    def test_a_fresh_home_and_a_published_sha_raise_nothing(self):              # test 11 (c), (b)
        self.assertFalse(self.h.drift_check()["new"])
        self.publish_event(self.own)
        self.assertTrue(self.h.drift_check()["known"])
        self.assertEqual(self.drifts(), [])

    def test_an_unknown_sha_alarms_once_then_publish_refuses_until_explained(self):   # test 11 (a)
        for r in ("curator", "envoy"):
            self.h.role_define("operator", r, "harness-ops", carry="none")
        cur = self.h.register(project="harness-ops", model=MODEL, task="t", role="curator")["id"]
        self.h.register(project="harness-ops", model=MODEL, task="t", role="envoy")
        self.publish_event("f" * 64)
        self.assertTrue(self.h.drift_check()["new"])
        for _ in range(10):
            self.h.drift_check()
        self.assertEqual(len(self.drifts()), 1)
        notes = [m for m in self.h.state().messages.values() if m.get("subject") == "harness drift"]
        self.assertEqual(len(notes), 1)
        with mock.patch.object(H.subprocess, "run", return_value=mock.Mock(stdout='{"ok": true, "failed": []}\n')):
            f, _ = self.h._release_gate(ROOT, "crew-coordinator", "9.9.9", self.h.state(), True)
        self.assertTrue(f and f[0].startswith("D installed code"))
        other = self.h.register(project="harness-ops", model=MODEL, task="t")["id"]
        with self.assertRaises(H.HarnessError):
            self.h.drift_explain(other, self.own[:12], "hand copy")
        self.h.drift_explain(cur, self.own[:12], "hand copy for a hotfix test")
        with mock.patch.object(H.subprocess, "run", return_value=mock.Mock(stdout='{"ok": true, "failed": []}\n')):
            f, _ = self.h._release_gate(ROOT, "crew-coordinator", "9.9.9", self.h.state(), True)
        self.assertEqual(f, [])

    def test_s4_b3_a_forged_pass_or_explanation_clears_nothing(self):              # critic S4 blocker 3 (F8)
        self.publish_event("f" * 64)
        agent = self.h.register(project="harness-ops", model=MODEL, task="t")["id"]
        self.h.store.append("release.sim", "system", {"ok": True, "code_sha": self.own})     # even a system-actor pass is not known-good
        self.h.store.append("release.sim", agent, {"ok": True, "code_sha": self.own})
        self.h.store.append("release.drift_explained", agent, {"code_sha": self.own, "reason": "forged"})
        st = self.h.state()
        self.assertNotIn(self.own, self.h.known_good_codes(st))
        self.assertNotIn(self.own, st.drift_explained)
        self.assertTrue(self.h.drift_check(st)["new"])

    def test_a_cp_p_copy_is_still_caught(self):                                       # test 11 (e): no mtime cache
        root = os.path.join(self.tmp, "inst")
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
        for d_, _, fs in os.walk(root):                                        # a frozen (0444) tree copies read-only
            os.chmod(d_, 0o755)
            for f_ in fs:
                os.chmod(os.path.join(d_, f_), 0o644)
        self.publish_event(H.code_sha(root, "plugin"))
        self.assertTrue(self.h.drift_check(root=root)["known"])
        p = os.path.join(root, "scripts", "doorbell.py")
        st_ = os.stat(p)
        with open(p, "a") as f:
            f.write("\n# hand patch\n")
        os.utime(p, ns=(st_.st_atime_ns, st_.st_mtime_ns))                            # cp -p keeps the old times
        self.assertTrue(self.h.drift_check(root=root)["new"])

    def test_the_drift_hash_is_fast(self):                                            # test 11 (d)
        t0 = time.time()
        H.code_sha(H.OWN_ROOT, "plugin")
        self.assertLess(time.time() - t0, 0.5)


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home, self.h = make_home(self.tmp)
        self.hm = os.environ["HOME"]

    def bash(self, cmd):
        return RG.pre_check({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.tmp}, self.home)

    def edit(self, path):
        return RG.pre_check({"tool_name": "Edit", "tool_input": {"file_path": path}, "cwd": self.tmp}, self.home)

    def test_h1_denies_writes_into_installed_copies(self):                          # acceptance test 5
        self.assertIn("H1", self.bash("cp x ~/.claude/plugins/cache/crew-coordinator/scripts/"))
        self.assertIn("H1", self.bash("echo hi > ~/.claude/plugins/cache/a.py"))
        self.assertIn("H1", self.bash(f"rsync -a src/ '{self.hm}/Library/Application Support/Claude/local-agent-mode-sessions/s1/rpm/cc/'"))
        self.assertIn("H1", self.bash(f"sed -i '' s/a/b/ {self.home}/_harness/bin/harness.py"))
        self.assertIsNone(self.bash("ls ~/.claude/plugins"))
        self.assertIsNone(self.bash("cp ~/.claude/plugins/cache/a.py /tmp/a.py"))     # copying OUT is fine
        self.assertIsNone(self.bash(f"cp a.json {self.home}/_harness/data/ontology-mapping.json"))   # local data stays editable

    def test_h1_protects_package_carried_data_only(self):
        with open(os.path.join(self.home, "_harness", "data", ".mirrored.json"), "w") as f:
            json.dump({"files": ["nouns.md"]}, f)
        self.assertIn("H1", self.bash(f"cp x {self.home}/_harness/data/nouns.md"))
        self.assertIsNone(self.bash(f"cp x {self.home}/_harness/data/lesson_cues.json"))

    def test_h2_denies_edits_to_a_published_tree_only(self):
        pub = os.path.join(self.tmp, "harness-hub", "crew-coordinator")
        os.makedirs(os.path.join(pub, ".claude-plugin"))
        open(os.path.join(pub, ".claude-plugin", "plugin.json"), "w").close()
        self.assertIn("H2", self.edit(os.path.join(pub, "scripts", "doorbell.py")))
        self.assertIsNone(self.edit(os.path.join(self.tmp, "specs", "cc0220-build", "scripts", "doorbell.py")))
        self.assertIsNone(self.edit(os.path.join(self.tmp, "harness-hub", "notes.md")))

    def test_h3_postcheck_after_a_publish(self):                                    # acceptance test 6
        pre = {"t": time.time() - 1, "code": "c" * 64, "hashes": RS.hash_tree(self.home), "carried": []}
        with open(os.path.join(self.home, "_harness", "release_prehash.json"), "w") as f:
            json.dump(pre, f)
        self.h.store.append("release.published", "human", {"name": "crew-coordinator", "version": "9", "code": "c" * 64})
        os.remove(os.path.join(self.home, LOCAL))
        inp = {"tool_name": "Bash", "tool_input": {"command": "python3 harness.py publish --build"}}
        out = RG.post_check(inp, self.home)
        self.assertIn("release.postcheck FAILED", out)
        ev = [e for e in self.h.store.read_all() if e["type"] == "release.postcheck"]
        self.assertFalse(ev[-1]["data"]["ok"])
        self.assertIsNone(RG.post_check(inp, self.home))                                # once per publish
        self.assertIsNone(RG.post_check({"tool_name": "Bash", "tool_input": {"command": "harness.py publish --dry-run"}}, self.home))

    def test_h3_ignores_a_publish_that_did_not_happen(self):
        pre = {"t": time.time() + 5, "hashes": {}, "carried": []}
        with open(os.path.join(self.home, "_harness", "release_prehash.json"), "w") as f:
            json.dump(pre, f)
        self.assertIsNone(RG.post_check({"tool_name": "Bash", "tool_input": {"command": "harness.py publish"}}, self.home))


if __name__ == "__main__":
    unittest.main()
