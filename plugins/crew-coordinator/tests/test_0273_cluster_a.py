"""0.27.3 cluster A: spend meter (item 1), auto-capsule (item 2), F3 subagent cap overrun (item 3). Run: python3 -B -m unittest tests.test_0273_cluster_a"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import harness as H, spend_meter as SM, subagent_cap as SC, mistake_ingest as MI, ctx_hook as CH, auto_capsule as AC

MODEL = "claude-sonnet-5-5"
SID = "abcd1234-0000-4000-8000-000000000001"


def usage_line(mid, i, o, cw, cr, tool=False):
    msg = {"id": mid, "model": MODEL, "usage": {"input_tokens": i, "output_tokens": o, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}}
    if tool:
        msg["content"] = [{"type": "tool_use", "name": "Bash"}]
    return json.dumps({"type": "assistant", "message": msg})


def write(p, lines):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("\n".join(lines) + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(os.path.join(self.home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})
        e.start()
        self.addCleanup(e.stop)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "ops-coder", "harness-ops")
        self.aid = self.h.register(project="harness-ops", model=MODEL)["id"]
        self.h.role_assign("operator", "ops-coder", self.aid)
        self.h.store.append("session.bound", self.aid, {"session_id": SID, "agent": self.aid})
        self.proj = os.path.join(self.tmp, "projects")
        self.tr = os.path.join(self.proj, "p1", SID + ".jsonl")


class SpendMeter(Base):
    def test_sum_counts_output_and_dedups_streamed_message(self):
        write(self.tr, [usage_line("m1", 10, 5, 100, 1000), usage_line("m1", 10, 40, 100, 1000), usage_line("m2", 1, 2, 3, 4)])
        c, last = SM.sum_usage(self.tr)
        self.assertEqual((c["in"], c["out"], c["cw"], c["cr"], last), (11, 42, 103, 1004, 3))
        self.assertEqual(SM.total(c), 1160)

    def test_gauge_is_unchanged_and_excludes_output(self):
        self.assertEqual(CH._usage_n({"input_tokens": 1, "output_tokens": 99, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3}), 6)

    def test_sample_writes_null_quota_once_per_interval_and_only_new_lines(self):
        write(self.tr, [usage_line("m1", 1, 2, 3, 4)])
        sf, sd = os.path.join(self.tmp, "st.json"), os.path.join(self.home, "_harness")
        r = SM.sample(SID, self.tr, "ops-coder", sf, sd, now=1000)
        self.assertEqual((r["tokens"], r["quota_pct"], r["unit"]), (10, None, "ops-coder"))
        self.assertIsNone(SM.sample(SID, self.tr, "ops-coder", sf, sd, now=1100))          # inside the 600 s window
        with open(self.tr, "a") as f:
            f.write(usage_line("m2", 5, 5, 0, 0) + "\n")
        self.assertEqual(SM.sample(SID, self.tr, "ops-coder", sf, sd, now=2000)["tokens"], 10)   # only the new message

    def test_sync_ingest_makes_spend_sample_events_with_null_quota(self):
        write(self.tr, [usage_line("m1", 1, 2, 3, 4)])
        SM.sample(SID, self.tr, "ops-coder", os.path.join(self.tmp, "st.json"), os.path.join(self.home, "_harness"), now=1000)
        self.assertEqual(self.h.ingest_spend_spool(), 1)
        ev = [e for e in self.h.store.read_all() if e["type"] == "spend.sample"]
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["actor"], ev[0]["data"]["tokens"], ev[0]["data"]["quota_pct"]), (self.aid, 10, None))
        self.assertEqual(self.h.ingest_spend_spool(), 0)                                    # spool consumed

    def test_subagent_transcript_is_never_sampled(self):
        p = os.path.join(self.proj, "p1", SID, "subagents", "agent-1.jsonl")
        write(p, [usage_line("m1", 1, 1, 1, 1)])
        self.assertIsNone(SM.sample(SID, p, "x", os.path.join(self.tmp, "s.json"), os.path.join(self.home, "_harness"), now=1000))


class AutoCapsule(Base):
    def test_auto_builds_capsule_through_the_normal_handoff_gates(self):
        self.h.state_note(self.aid, "Finish the spend meter review.\nMore detail here.")
        out = self.h.handoff(self.aid, "auto")
        self.assertIn("capsule", out)
        txt = open(self.h._home_file(out["capsule"], "x")).read()
        self.assertIn("## Next action\n- Finish the spend meter review.", txt)
        self.assertIn("model:", txt.split("\n", 3)[1] + txt[:80])                             # the model stamp the normal path adds
        self.assertTrue(self.h.state().agents[self.aid].get("handed_off"))

    def test_cap_holds_and_oversize_note_is_cut(self):
        self.h.state_note(self.aid, "x" * 900 + "\n" + "y" * 250)
        t = AC.build(self.h, self.aid)
        self.assertLessEqual(len(t), AC.MAX_CHARS)
        self.assertIsNone(H.check_capsule_budget(t))

    def test_git_section_is_read_only_and_fails_soft(self):
        self.assertEqual(AC.git_lines(None, AC.GIT[0], 5), [])
        self.assertEqual(AC.git_lines(self.tmp, ("push",), 5), [])                          # only status and log run
        self.assertIn("no repository", AC.build(self.h, self.aid, os.path.join(self.tmp, "nope")))
        subprocess.run(["git", "init", "-q", self.tmp], check=True)
        before = subprocess.run(["git", "-C", self.tmp, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertIn("## Git", AC.build(self.h, self.aid, self.tmp))
        self.assertEqual(before, subprocess.run(["git", "-C", self.tmp, "status", "--porcelain"], capture_output=True, text=True).stdout)

    def test_plain_capsule_text_still_works_and_bad_text_still_refused(self):
        with self.assertRaises(H.HarnessError):
            self.h.handoff(self.aid, "no heading here")


class SubagentCap(Base):
    def sub(self, lines, name="agent-a1b2"):
        p = os.path.join(self.proj, "p1", SID, "subagents", name + ".jsonl")
        write(p, lines)
        write(self.tr, [usage_line("top", 1, 1, 0, 0)])

    def test_overrun_at_1_5x_files_one_candidate_once(self):
        self.sub([usage_line("a", 100, 100, 0, 0, tool=True)] * 1 + [usage_line("b", 100, 100, 0, 0, tool=True), usage_line("c", 100, 100, 0, 0, tool=True)])
        SC.write_cap(self.home, SID, "agent-a1b2", "mechanical scan", cap_tokens=400)         # 600 counted / 400 = 1.5
        self.assertEqual(self.h.scan_subagent_caps(self.proj), 1)
        notes = [e for e in self.h.store.read_all() if e["type"] == "corpus.recorded" and "candidate" in (e["data"].get("tags") or [])]
        self.assertEqual(len(notes), 1)
        self.assertIn("1.5x", notes[0]["data"]["title"])
        self.assertEqual(self.h.scan_subagent_caps(self.proj), 0)                           # done mark: never twice

    def test_under_1_5x_files_nothing(self):
        self.sub([usage_line("a", 100, 100, 0, 0, tool=True)])
        SC.write_cap(self.home, SID, "agent-a1b2", "x", cap_tokens=400)                      # 200 / 400 = 0.5
        self.assertEqual(self.h.scan_subagent_caps(self.proj), 0)

    def test_call_cap_overrun_counts_tool_calls(self):
        self.sub([usage_line("m%d" % i, 1, 1, 0, 0, tool=True) for i in range(6)])
        SC.write_cap(self.home, SID, "agent-a1b2", "calls", cap_calls=4)                     # 6 / 4 = 1.5
        self.assertEqual(self.h.scan_subagent_caps(self.proj), 1)

    def test_bad_cap_args_and_stale_and_missing_transcript(self):
        with self.assertRaises(ValueError):
            SC.write_cap(self.home, SID, "agent-a1b2", "none")                               # no cap set
        p = SC.write_cap(self.home, SID, "agent-zz99", "ghost", cap_tokens=1)                # no subagent transcript on disk
        self.assertEqual(SC.overruns(self.home, self.proj), [])
        os.utime(p, (1, 1))
        self.assertEqual(SC.read_caps(self.home), [])                                        # older than 14 days


if __name__ == "__main__":
    unittest.main()
