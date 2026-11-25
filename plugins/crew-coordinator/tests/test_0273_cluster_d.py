"""0.27.3 cluster D: dreams_guard (PreToolUse write guard for the 99_dreams folder) and its hooks.json registration, plus the propose_hook entry.
Temp HOME only; the real 99_dreams folder is never touched. Run: python3 -B -m unittest tests.test_0273_cluster_d"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import io, json, os, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import dreams_guard as G

HOOKS = os.path.join(HERE, "..", "hooks", "hooks.json")


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dg-")
        self.dreams = os.path.join(self.home, "Claude", "99_dreams")
        self.lucid = os.path.join(self.home, "Claude", "Code", "lucid")
        self.other = os.path.join(self.home, "Claude", "Code", "other")
        for d in (self.dreams, self.lucid, self.other):
            os.makedirs(d)
        self.env = mock.patch.dict(os.environ, {"HOME": self.home, "HARNESS_STATE_DIR": os.path.join(self.home, "state")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_hook(self, tool, ti, cwd=None):
        out = io.StringIO()
        with mock.patch.object(G, "record") as rec, mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "s", "cwd": cwd or self.other, "tool_name": tool, "tool_input": ti}))), \
                mock.patch("sys.stdout", out):
            rc = G.main()
        self.assertEqual(rc, 0)
        o = out.getvalue()
        return (json.loads(o)["hookSpecificOutput"]["permissionDecision"] if o else None), rec

    def f(self, name="a.md"):
        return os.path.join(self.dreams, name)


class T(Base):
    def test_refused_from_another_cwd(self):
        for tool, ti in (("Write", {"file_path": self.f()}), ("Edit", {"file_path": self.f()}), ("NotebookEdit", {"notebook_path": self.f("n.ipynb")})):
            v, rec = self.run_hook(tool, ti)
            self.assertEqual(v, "deny", tool)
            rec.assert_called_once()

    def test_allowed_from_lucid_and_its_subfolder(self):
        sub = os.path.join(self.lucid, "scripts"); os.makedirs(sub)
        for cwd in (self.lucid, sub):
            self.assertIsNone(self.run_hook("Write", {"file_path": self.f()}, cwd)[0])
            self.assertIsNone(self.run_hook("Bash", {"command": f"echo x > {self.f()}"}, cwd)[0])

    def test_reads_and_unrelated_writes_allowed(self):
        for cmd in (f"cat {self.f()}", f"ls {self.dreams} | head", f"grep x {self.f()} > {self.home}/out.txt", f"cp {self.f()} {self.home}/copy.md",
                    "echo hi > /tmp/x.txt"):
            self.assertIsNone(self.run_hook("Bash", {"command": cmd})[0], cmd)
        for tool in ("Read", "Grep", "Glob"):
            self.assertIsNone(self.run_hook(tool, {"file_path": self.f()})[0])
        self.assertIsNone(self.run_hook("Write", {"file_path": os.path.join(self.other, "ok.md")})[0])

    def test_path_tricks_refused(self):
        os.symlink(self.dreams, os.path.join(self.other, "link"))
        for p in (os.path.join(self.other, "link", "a.md"), os.path.join(self.other, "..", "..", "99_dreams", "a.md"),
                  "~" + "/Claude/99_dreams/a.md", os.path.join(self.dreams, "x", "..", "a.md"), os.path.join(self.dreams, "new", "deep", "a.md")):
            self.assertEqual(self.run_hook("Write", {"file_path": p})[0], "deny", p)
        self.assertEqual(self.run_hook("Write", {"file_path": "../99_dreams/a.md"}, os.path.join(self.home, "Claude", "Code"))[0], "deny")
        self.assertEqual(self.run_hook("Write", {"file_path": "../../99_dreams/a.md"}, self.lucid)[0], None)

    def test_bash_writes_refused(self):
        os.symlink(self.dreams, os.path.join(self.other, "link"))
        cmds = [f"echo x > {self.f()}", f"echo x >> {self.f()}", f"echo x>{self.f()}", f"echo x | tee {self.f()}", f"mv /tmp/a {self.f()}", f"mv {self.f()} /tmp/a",
                f"cp /tmp/a {self.f()}", f"rm {self.f()}", f"rm -rf {self.dreams}", f"sed -i s/a/b/ {self.f()}", "echo x > ~" + "/Claude/99_dreams/a.md",
                "echo x > $HOME" + "/Claude/99_dreams/a.md", f"touch {self.f('b')}", "echo x > link/a.md", f"cd {self.dreams} && echo x > a.md",
                f"ls; true && printf y 2>> {self.f()}", f"dd if=/dev/zero of={self.f()} count=1", f"cp -t {self.dreams} /tmp/a"]
        for c in cmds:
            self.assertEqual(self.run_hook("Bash", {"command": c})[0], "deny", c)

    def test_fail_open_on_error(self):
        for bad in ("not json", "[]", ""):
            with mock.patch("sys.stdin", io.StringIO(bad)), mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(G.main(), 0)
                self.assertEqual(out.getvalue(), "")
        with mock.patch.object(G, "targets", side_effect=RuntimeError("boom")):
            v, _ = self.run_hook("Write", {"file_path": self.f()})
        self.assertIsNone(v)
        self.assertIn("boom", open(os.path.join(self.home, "state", "dreams-guard.log")).read())

    def test_event_failure_still_denies(self):
        with mock.patch.dict(sys.modules, {"harness": None}):
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(json.dumps({"cwd": self.other, "tool_name": "Write", "tool_input": {"file_path": self.f()}}))), mock.patch("sys.stdout", out):
                G.main()
        self.assertIn("deny", out.getvalue())

    def test_refusal_writes_ledger_event(self):
        import harness as H
        ex = os.path.join(self.home, "Exchange"); os.makedirs(ex)
        with mock.patch.dict(os.environ, {"HARNESS_HOME": ex}):
            hh = H.Harness(ex)
            with mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "zz", "cwd": self.other, "tool_name": "Write", "tool_input": {"file_path": self.f(), "content": "SECRET"}}))), \
                    mock.patch("sys.stdout", io.StringIO()):
                G.main()
            ev = [e for e in hh.store.read_all() if e.get("type") == "dreams.write_refused"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["data"]["path"], os.path.realpath(self.f()))
        self.assertNotIn("SECRET", json.dumps(ev[0]))

    def test_hooks_json_registers_both_once(self):
        d = json.load(open(HOOKS))["hooks"]
        def hits(ev, name):
            return [(g["matcher"], h) for g in d[ev] for h in g["hooks"] if name in h["command"]]
        pre, post = hits("PreToolUse", "dreams_guard.py"), hits("PostToolUse", "propose_hook.py")
        self.assertEqual(len(pre), 1); self.assertEqual(len(post), 1)
        self.assertEqual(pre[0][0], "Write|Edit|MultiEdit|NotebookEdit|Bash")
        self.assertIn("MultiEdit", pre[0][0].split("|"))
        self.assertEqual(post[0][0], "AskUserQuestion")
        self.assertEqual(post[0][1], {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/propose_hook.py"', "timeout": 10})
        self.assertEqual(sum(h["command"].count("dreams_guard.py") + h["command"].count("propose_hook.py") for ev in d.values() for g in ev for h in g["hooks"]), 2)
        for n in ("dreams_guard.py", "propose_hook.py"):
            self.assertTrue(os.path.isfile(os.path.join(HERE, "..", "scripts", n)))


class Cluster0273F(Base):
    """0.27.3 F: stream redirects, MultiEdit, and the Bash forms added by N1. Temp dirs only. """
    def deny(self, cmd, cwd=None):
        self.assertEqual(self.run_hook("Bash", {"command": cmd}, cwd)[0], "deny", cmd)

    def allow(self, cmd, cwd=None):
        self.assertIsNone(self.run_hook("Bash", {"command": cmd}, cwd)[0], cmd)

    def test_f_streams_are_not_files(self):
        for c in ("ls 2>&1", "cat a 2>&1 | head", "echo hi >&2", "grep x * > /dev/null 2>&1", "rm -f /tmp/zz 2>&1", "ls >&-"):
            self.allow(c, self.dreams)
        self.allow("ls 2>&1", os.path.join(self.dreams, "sub") if os.makedirs(os.path.join(self.dreams, "sub")) is None else None)

    def test_f_real_redirect_still_refused_beside_a_stream(self):
        self.deny("echo x > a.md 2>&1", self.dreams)
        self.deny(f"echo x 2>&1 > {self.f()}")
        self.deny("echo x 2> err.txt", self.dreams)

    def test_f_multiedit_refused_and_matcher_has_it(self):
        v, rec = self.run_hook("MultiEdit", {"file_path": self.f(), "edits": []})
        self.assertEqual(v, "deny"); rec.assert_called_once()
        self.assertIsNone(self.run_hook("MultiEdit", {"file_path": os.path.join(self.other, "ok.md"), "edits": []})[0])
        self.assertIn("MultiEdit", [g["matcher"] for g in json.load(open(HOOKS))["hooks"]["PreToolUse"] if "dreams_guard" in g["hooks"][0]["command"]][0].split("|"))

    def test_f_groups(self):
        self.deny(f"(cd {self.dreams} && echo x > a.md)")
        self.deny(f"{{ cd {self.dreams}; echo x > a.md; }}")
        self.deny(f"(cd {self.dreams} && touch b)")
        self.deny(f"{{ cd {self.dreams}; rm a.md; }}")
        self.allow(f"(cd {self.dreams} && ls) ; echo x > out.txt")       # the cd ended with the group
        self.allow(f"(cd {self.home} && echo x > out.txt)")

    def test_f_env_wrapper(self):
        self.deny(f"env VAR=1 tee {self.f()}")
        self.deny(f"echo x | env -i VAR=1 tee {self.f()}")
        self.deny(f"sudo env A=1 rm {self.f()}")
        self.allow(f"env VAR=1 tee {self.home}/out.txt")

    def test_f_destination_flags(self):
        for c in (f"curl -o {self.f()} http://x", f"curl --output {self.f()} http://x", f"curl -o{self.f()} http://x", f"wget -O {self.f()} http://x",
                  f"wget --output-document={self.f()} http://x", f"wget -P {self.dreams} http://x", f"tar -xf a.tar -C {self.dreams}", f"tar xzf a.tgz -C {self.dreams}",
                  f"tar --extract --directory={self.dreams} -f a.tar", f"tar czf {self.f('o.tgz')} src", f"tar -cf {self.f('o.tar')} src",
                  f"git clone http://x/r.git {self.f('r')}", f"git clone --depth 1 -b main http://x/r.git {self.f('r')}", f"git -C {self.dreams} clone http://x/r.git",
                  f"find {self.dreams} -name '*.tmp' -delete", f"find {self.dreams} -delete"):
            self.deny(c)
        self.deny("git clone http://x/r.git", self.dreams)           # derived destination lands in the cwd
        self.deny("find . -name x -delete", self.dreams)

    def test_f_destination_forms_outside_are_allowed(self):
        for c in (f"curl -o {self.home}/o http://x", f"curl http://x/{self.f()}", f"wget -O {self.home}/o http://x", f"tar -xf {self.f('a.tar')} -C {self.home}",
                  f"tar -cf {self.home}/o.tar -C {self.dreams} .", f"tar -tf {self.f('a.tar')}", f"git clone {self.dreams} {self.home}/copy",
                  f"find {self.dreams} -name x", f"find {self.home} -delete"):
            self.allow(c)


if __name__ == "__main__":
    unittest.main()
