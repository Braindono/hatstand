"""cc 0.17.0 R-055 refresh-noise cleanups: long-expired leases leave the Do lines, reload fixes fold into one line, the
owed-reply tail is a count plus the newest 3, the send ladder is short, nudge caps are raised.
Run: python3 -B tests/test_c170_r055.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, tempfile, time, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import doorbell as D

MODEL = "claude-opus-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "Exchange")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.a = self.h.register(project="orch", model=MODEL)["id"]
        self.b = self.h.register(project="orch", model=MODEL)["id"]


class Leases(Base):
    def lease(self, name, expired_s):
        p = os.path.join(self.home, name)
        open(p, "w").write("x")
        self.h.claim(self.a, p, intent="edit")
        st = self.h.state()
        key = [k for k in st.leases if k.endswith(name)][0]
        return key, time.time() + expired_s

    def test_recent_expiry_kept_long_expiry_dropped(self):
        k1, _ = self.lease("recent.md", 0)
        k2, _ = self.lease("old.md", 0)
        real = H.State._apply_event

        def aged(st_self, ev):          # backdate the two claims: one expired 1 h ago, one 2 days ago
            real(st_self, ev)
            if ev.get("type") == "lease.claimed":
                L = st_self.leases.get(ev["data"].get("path"))
                if L:
                    L["expires_t"] = time.time() - (3600 if L["path"].endswith("recent.md") else 2 * 86400)
        with mock.patch.object(H.State, "_apply_event", aged), mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"}):
            t = self.h.sync(self.a, do_only=True)["text"]
        self.assertIn("recent.md expired: renew", t)
        self.assertNotIn("old.md", t)


class ReloadLine(Base):
    def test_reload_fixes_fold_into_one_line_and_generic_line_dropped(self):
        flags = ["reload: alpha 0.1.0 running, 0.1.1 published (harness_admin op=reload)",
                 "reload: beta 0.2.0 running, 0.3.0 published (harness_admin op=reload)",
                 "install ▼ gamma 0.1 -> 0.2: claude plugin update gamma@harness-local"]
        with mock.patch.object(H, "drift_lines", return_value={"lines": [], "flags": flags}), \
                mock.patch.object(H, "health_rows", return_value=([], 2)):
            t = self.h.sync(self.a, do_only=True)["text"]
        self.assertIn("✕ reload: 2 plugins behind (alpha 0.1.0→0.1.1, beta 0.2.0→0.3.0): harness_admin op=reload", t)
        self.assertEqual(t.count("reload:"), 1)
        self.assertIn("install ▼ gamma", t)
        self.assertNotIn("plugin behind registry or missing", t)

    def test_single_reload_stays_as_it_was(self):
        flags = ["reload: alpha 0.1.0 running, 0.1.1 published (harness_admin op=reload)"]
        with mock.patch.object(H, "drift_lines", return_value={"lines": [], "flags": flags}), \
                mock.patch.object(H, "health_rows", return_value=([], 0)):
            t = self.h.sync(self.a, do_only=True)["text"]
        self.assertIn("✕ reload: alpha 0.1.0 running, 0.1.1 published (harness_admin op=reload)", t)

    def test_generic_line_without_specific_fixes(self):
        with mock.patch.object(H, "drift_lines", return_value={"lines": [], "flags": []}), \
                mock.patch.object(H, "health_rows", return_value=([], 2)):
            t = self.h.sync(self.a, do_only=True)["text"]
        self.assertIn("plugin behind registry or missing", t)


class OwedTail(Base):
    def test_count_and_newest_three(self):
        ids = [self.h.send(self.a, self.b, f"task {i}", kind="task")["id"] for i in range(5)]
        t = self.h.inbox(self.b, mark_read=False)["text"]
        self.assertIn(f"owed reply 5: {ids[4]} {ids[3]} {ids[2]} +2 older (harness_admin op=thread)", t)
        for old in ids[:2]:
            self.assertNotIn(old, t.splitlines()[-1])


class LadderAndCaps(Base):
    def test_short_ladder(self):
        r = self.h.send(self.a, self.b, "do x", kind="task")
        lad = r["ladder"]
        self.assertEqual(set(lad), {"waits", "max_wait", "end", "how"})
        self.assertLess(len(lad["how"]), 100)

    def test_raised_cap_defaults(self):
        self.assertEqual((D.DEFAULTS["nudge_per_agent_hour"], D.DEFAULTS["nudge_per_pair_hour"], D.DEFAULTS["global_per_hour"]),
                         (10, 6, 30))


class ConfigLine(Base):
    def test_desktop_config_alone_does_not_raise_the_do_line(self):
        self.h.sync(self.a, do_only=True)
        fp = H.config_fingerprint(self.home)
        for key, expect in (("claude-desktop:config", False), ("claude-code:plugins", True)):
            changed = dict(fp, **{key: "f" * 64})
            with mock.patch.object(H, "config_fingerprint", return_value=changed):
                t = self.h.sync(self.a, do_only=True)["text"]
            self.assertEqual("⚙ Claude config/plugins changed" in t, expect, key)
            with mock.patch.object(H, "config_fingerprint", return_value=changed):
                self.h.sync(self.a, do_only=True)     # new baseline before the next key


class Usage(Base):
    def test_ranking_by_peak_ctx_per_day(self):
        self.h.sync(self.a, ctx=300000)
        self.h.sync(self.a, ctx=450000)
        self.h.sync(self.b, ctx=120000)
        self.h.sync(self.b)                       # no ctx: not counted
        u = self.h.usage_ranking(1)
        rows = u["days"][0]["rows"]
        self.assertEqual([(r["agent"], r["peak_ctx"], r["syncs"]) for r in rows], [(self.a[:8], 450000, 2), (self.b[:8], 120000, 1)])
        self.assertIn("not cumulative spend", u["note"])

    def test_cli_prints_ranking(self):
        import io, contextlib
        self.h.sync(self.a, ctx=200000)
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HARNESS_HOME": self.home}), contextlib.redirect_stdout(buf):
            H.main(["usage", "--days", "1"])
        self.assertIn("200k", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
