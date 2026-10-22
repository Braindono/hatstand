"""cc 0.15.1 Wave 2: pinned corpus_index.py, dashboard hardening + approve buttons, CLI override gate, sync Do-line.
Run: python3 -B tests/test_cc151_w2.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, http.client, json, os, subprocess, sys, tempfile, threading, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import mcp_server as M
import dashboard_server as D
from test_cc151_w1 import Base, MODEL
from test_release_gates import _mk

FAKE = "import sys\nprint('exit ok', sys.argv[1:])\nsys.exit(0)\n"


class PinBase(Base):
    def setUp(self):
        super().setUp()
        self.sdir = os.path.join(self.home, "projects", "orchestration", "scripts")
        os.makedirs(os.path.join(self.sdir, "rules"))
        self.script = os.path.join(self.sdir, "corpus_index.py")
        with open(self.script, "w") as f:
            f.write(FAKE)
        with open(os.path.join(self.sdir, "rules", "r1.py"), "w") as f:
            f.write("X = 1\n")
        self.cur = self.h.corpus_index_digests()
        self.h.pin_corpus_index("operator", self.cur["sha"], self.cur["rules"], "m-" + "a" * 12)


class Pin(PinBase):
    def test_pin_ok_runs(self):
        r = self.h.run_corpus_index(["--check"], 10)
        self.assertEqual(r.returncode, 0)
        self.assertIn("exit ok", r.stdout)

    def test_planted_script_not_executed(self):
        marker = os.path.join(self.tmp, "ran")
        with open(self.script, "w") as f:
            f.write(f"open({marker!r}, 'w').write('x')\n")
        with self.assertRaises(H.HarnessError) as c:
            self.h.run_corpus_index(["--check"], 10)
        new = self.h.corpus_index_digests()["sha"]
        self.assertIn(new, str(c.exception))
        self.assertIn(self.cur["sha"], str(c.exception))
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(self.h._corpus_check(None)[0].startswith("corpus: ▲ S5:"))

    def test_changed_rules_blocks(self):
        with open(os.path.join(self.sdir, "rules", "r2.py"), "w") as f:
            f.write("Y = 2\n")
        with self.assertRaises(H.HarnessError) as c:
            self.h.run_corpus_index(["--check"], 10)
        self.assertIn("rules digest", str(c.exception))

    def test_underscore_rule_files_ignored(self):
        with open(os.path.join(self.sdir, "rules", "_helper.py"), "w") as f:
            f.write("Z = 3\n")
        self.assertEqual(self.h.run_corpus_index(["--check"], 10).returncode, 0)

    def test_s5_proof_path_refuses_on_mismatch(self):
        steward = self.agent("corpus-steward")
        with open(self.script, "a") as f:
            f.write("# tampered\n")
        with self.assertRaisesRegex(H.HarnessError, r"S5: corpus_index.py sha .* != pinned"):
            self.h._require_proof(self.h.state(), steward, "done exit=0 hash=abcdef12")

    def test_default_pin_without_event(self):
        h2 = H.Harness(os.path.join(self.tmp, "h2"))
        self.assertEqual(h2.corpus_index_pin(), H.CORPUS_INDEX_PIN)
        self.assertEqual(H.CORPUS_INDEX_PIN, {"sha": "4aa80ffa28ad", "rules": "46a6d5694950"})

    def test_pin_update_roles(self):
        bare, steward, envoy = self.agent(), self.agent("corpus-steward"), self.agent("corpus-envoy")
        args = {"sha": "b" * 12, "rules": "c" * 12, "ref": "m-" + "d" * 12}
        n0 = len(self.types("corpus_index.pinned"))
        self.as_(bare)
        self.assertIn("pending", self.adm("pin_corpus_index", bare, **args))
        self.as_(steward)
        self.assertIn("pending", self.adm("pin_corpus_index", steward, **args))
        self.assertEqual(len(self.types("corpus_index.pinned")), n0)
        self.as_(envoy)
        r = self.adm("pin_corpus_index", envoy, **args)
        self.assertEqual(r["pinned"], {"sha": "b" * 12, "rules": "c" * 12})
        self.assertEqual(len(self.types("corpus_index.pinned")), n0 + 1)
        self.assertEqual(self.h.corpus_index_pin()["sha"], "b" * 12)   # visible to the next run
        with self.assertRaises(H.HarnessError):
            self.h.run_corpus_index(["--check"], 10)

    def test_pending_pin_approved_writes_event(self):
        bare = self.as_(self.agent())
        r = self.adm("pin_corpus_index", bare, sha="e" * 12, rules="f" * 12, ref="m-" + "1" * 12)
        self.approve(r["pending"])
        self.assertEqual(self.h.corpus_index_pin()["rules"], "f" * 12)

    def test_bad_format_refused(self):
        envoy = self.as_(self.agent("corpus-envoy"))
        for kw in ({"sha": "xyz", "rules": "c" * 12, "ref": "m-" + "d" * 12},
                   {"sha": "b" * 12, "rules": "C" * 12, "ref": "m-" + "d" * 12},
                   {"sha": "b" * 12, "rules": "c" * 12, "ref": "nope"}):
            with self.assertRaises(H.HarnessError):
                self.adm("pin_corpus_index", envoy, **kw)
        bare = self.as_(self.agent())
        with self.assertRaises(H.HarnessError):
            self.adm("pin_corpus_index", bare, sha="zz", rules="c" * 12, ref="m-" + "d" * 12)

    def test_isolated_flag_in_argv(self):
        with mock.patch.object(H.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            self.h.run_corpus_index(["--check"], 5)
        argv = run.call_args[0][0]
        self.assertEqual(argv[:3], [sys.executable, "-I", self.script])

    def test_pin_known_to_curation_roles_typecheck(self):
        self.assertIn("pin_corpus_index", H.CURATION_ACTIONS)
        self.assertIn("pin_corpus_index", H.curation_roles(self.home)["envoy"])
        self.assertNotIn("pin_corpus_index", H.curation_roles(self.home)["steward"])

    def test_health_line(self):
        import health
        self.assertIn("● corpus_index.py pin ok", health.text(health.health(self.h)))
        with open(self.script, "a") as f:
            f.write("# x\n")
        self.assertIn("▲ corpus_index.py pin MISMATCH (script)", health.text(health.health(self.h)))


class Dash(Base):
    def setUp(self):
        super().setUp()
        self.srv, self.tok = D.make_server(self.h, "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def req(self, method, path, host=None, headers=None, body=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest(method, path, skip_host=True)
        c.putheader("Host", host or f"127.0.0.1:{self.port}")
        hd = dict(headers or {})
        if token is True and method == "POST":
            hd["X-CSRF-Token"] = self.tok
        elif token:
            hd["X-CSRF-Token"] = token
        for k, v in hd.items():
            c.putheader(k, v)
        if body is not None:
            if "Content-Length" not in hd:
                c.putheader("Content-Length", str(len(body)))
            c.putheader("Content-Type", "application/json")
        c.endheaders(body.encode() if body is not None else None)
        r = c.getresponse()
        data = r.read().decode()
        return r.status, dict(r.getheaders()), data

    def pending(self):
        a = self.agent()
        self.as_(a)
        r = self.adm("set_project", a, target=a, project="orch-two")
        return a, r["pending"], next(x for x in self.h.approvals(True) if x["id"] == r["pending"])

    def test_foreign_host_403(self):
        self.assertEqual(self.req("GET", "/operator", host="evil.example:80")[0], 403)
        self.assertEqual(self.req("GET", "/api/state", host=f"localhost:{self.port + 1}")[0], 403)
        self.assertEqual(self.req("GET", "/operator", host=f"localhost:{self.port}")[0], 200)
        self.assertEqual(self.req("POST", "/api/deny", host="evil:1", body="{}")[0], 403)

    def test_csrf_required_on_post(self):
        _, pid, _ = self.pending()
        b = json.dumps({"id": pid})
        self.assertEqual(self.req("POST", "/api/deny", body=b, token=False)[0], 403)
        self.assertEqual(self.req("POST", "/api/deny", body=b, token="0" * 32)[0], 403)
        self.assertEqual(len(self.h.approvals(True)), 1)
        self.assertEqual(self.req("POST", "/api/deny", body=b)[0], 200)
        self.assertEqual(len(self.h.approvals(True)), 0)

    def test_origin_must_match(self):
        self.assertEqual(self.req("POST", "/api/deny", body="{}", headers={"Origin": "http://evil.example"})[0], 403)

    def test_non_loopback_host_refused(self):
        with self.assertRaises(ValueError):
            D.make_server(self.h, "0.0.0.0", 0)
        self.assertEqual(D.serve(self.h, "192.168.1.5", 0), 2)

    def test_content_length_limits(self):
        s, _, _ = self.req("POST", "/api/deny", headers={"Content-Length": "999999"}, body="")
        self.assertEqual(s, 413)
        self.assertEqual(self.req("POST", "/api/deny", headers={"Content-Length": "abc"}, body="")[0], 400)
        self.assertEqual(self.req("POST", "/api/deny", headers={"Content-Length": "-5"}, body="")[0], 400)
        self.assertEqual(self.req("POST", "/api/deny", headers={"Transfer-Encoding": "chunked"}, body="")[0], 400)

    def test_security_headers_and_token_embedded(self):
        s, hd, body = self.req("GET", "/")
        hd = {k.lower(): v for k, v in hd.items()}
        self.assertEqual(hd["x-frame-options"], "DENY")
        self.assertEqual(hd["x-content-type-options"], "nosniff")
        self.assertEqual(hd["referrer-policy"], "no-referrer")
        self.assertEqual(hd["cache-control"], "no-store")
        self.assertEqual(hd["content-security-policy"], "default-src 'self' 'unsafe-inline'")
        self.assertIn(f'name="csrf-token" content="{self.tok}"', body)
        self.assertIn(self.tok, self.req("GET", "/operator")[2])
        self.assertEqual(self.req("GET", "/nope")[1].get("X-Frame-Options"), "DENY")

    def test_approve_once_logged_dashboard(self):
        a, pid, rec = self.pending()
        page = self.req("GET", "/operator")[2]
        self.assertIn(pid, page)
        self.assertIn(rec["args_digest"][:4], page)
        self.assertNotIn(f'value="{rec["args_digest"][:4]}"', page)   # the code is typed, never prefilled
        s, _, b = self.req("POST", "/api/approve", body=json.dumps({"id": pid, "code": rec["args_digest"][:4]}))
        self.assertEqual(s, 200, b)
        self.assertEqual(self.h.state().agents[a]["project"], "orch-two")
        g = self.types("approval.granted")[-1]["data"]
        self.assertEqual((g["id"], g["channel"]), (pid, "dashboard"))
        s2, _, _ = self.req("POST", "/api/approve", body=json.dumps({"id": pid, "code": rec["args_digest"][:4]}))
        self.assertEqual(s2, 400)
        self.assertEqual(len(self.types("approval.granted")), 1)

    def test_wrong_code_does_nothing(self):
        a, pid, _ = self.pending()
        s, _, _ = self.req("POST", "/api/approve", body=json.dumps({"id": pid, "code": "zzzz"}))
        self.assertEqual(s, 400)
        self.assertEqual(self.h.state().agents[a]["project"], "orch")
        self.assertEqual(len(self.h.approvals(True)), 1)

    def test_deny_works(self):
        _, pid, _ = self.pending()
        s, _, _ = self.req("POST", "/api/deny", body=json.dumps({"id": pid}))
        self.assertEqual(s, 200)
        self.assertEqual(self.types("approval.denied")[-1]["data"]["channel"], "dashboard")

    def test_archive_pin_behind_csrf(self):
        a = self.agent()
        n = self.note(a)
        self.assertEqual(self.req("POST", "/api/pin", body="id=" + n, token=False)[0], 403)
        s, _, b = self.req("POST", "/api/pin", body="id=" + n + "&reason=%22rule%20line%20text%22",
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertIn(s, (200, 400), b)


class CliOverride(Base):
    def run_cli(self, args, env_extra=None):
        env = dict(os.environ, HARNESS_HOME=self.home, HARNESS_CACHE=os.path.join(self.tmp, "cache"))
        env.pop("HARNESS_NONINTERACTIVE_OVERRIDE", None)
        env.update(env_extra or {})
        script = os.path.join(HERE, "..", "scripts", "harness.py")
        return subprocess.run([sys.executable, "-B", script, "--home", self.home] + args, capture_output=True, text=True,
                              env=env, stdin=subprocess.DEVNULL)

    def setUp(self):
        super().setUp()
        self.h, self.envoy, self.lead, self.plug, self.pkg, self.sha = _mk(tempfile.mkdtemp())
        self.home = self.h.home

    def test_override_needs_tty(self):
        n = len(self.h.store.read_all())
        p = self.run_cli(["publish", self.plug, "--pkg", self.pkg, "--operator-override", "ship"])
        self.assertEqual(p.returncode, 2)
        self.assertIn("override needs an interactive terminal", p.stdout)
        self.assertEqual(len(H.Harness(self.home).store.read_all()), n)

    def test_env_escape_tags_event(self):
        p = self.run_cli(["publish", self.plug, "--pkg", self.pkg, "--operator-override", "ship"],
                         {"HARNESS_NONINTERACTIVE_OVERRIDE": "1"})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        ev = [e for e in H.Harness(self.home).store.read_all() if e["type"] == "release.published"][-1]
        self.assertEqual((ev["data"]["via"], ev["data"]["channel"]), ("cli", "cli-env"))

    def test_normal_publish_not_gated(self):
        a = self.h.send(self.envoy, "operator", f"ACCEPT sha={self.sha[:12]}")["id"]
        p = self.run_cli(["publish", self.plug, "--pkg", self.pkg, "--accept", a])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        ev = [e for e in H.Harness(self.home).store.read_all() if e["type"] == "release.published"][-1]
        self.assertNotIn("channel", ev["data"])

    def test_method_level_unchanged(self):
        out = self.h.publish_release(self.plug, pkg=self.pkg, override="r", by=None)
        self.assertIn("gate overridden by operator", out["warn"])


class Small(Base):
    def test_deferred_grant_bound_to_args_digest(self):
        a = self.as_(self.agent())
        r = self.adm("reload", a, force=True)
        self.approve(r["pending"])
        self.assertIsNone(self.h.consume_approval(a, "reload_force", {"x": 1}))   # different args: grant untouched
        self.assertIsNotNone(self.h.consume_approval(a, "reload_force", {}))
        self.assertIsNone(self.h.consume_approval(a, "reload_force", {}))

    def test_sync_do_line_for_pending(self):
        a = self.as_(self.agent())
        b = self.agent()
        self.adm("set_project", a, target=a, project="orch-two")
        for who in (b, a):
            t = self.h.sync(who)["text"]
            self.assertIn("▲ 1 approval request(s): harness.py pending", t)
            self.assertNotIn("orch-two", t)
        self.assertIn("approval request", self.h.sync(b, do_only=True)["text"])

    def test_no_do_line_without_pending(self):
        self.assertNotIn("approval request", self.h.sync(self.agent())["text"])


if __name__ == "__main__":
    unittest.main()
