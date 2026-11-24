"""0.27.2 matrix rows for I3 (dated switches: no shipped date, one clock, a warning at 14 days). Each ROWS entry is one row of the I3 table: fn(testcase).
Depends on: scripts/dated_switches.py, ask_gate.py, idcheck.py, harness.py (alias table, sync), data/role-aliases.json."""
import ast, contextlib, io, json, os, re, shutil, subprocess, sys, tempfile, time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ask_gate as G
import dated_switches as D
import harness as H
import idcheck

FROZEN = "2026-11-24"          # the release day: the frozen clock of the scan rows


def tmpdir(tc):
    d = tempfile.mkdtemp(prefix="i3-")
    tc.addCleanup(shutil.rmtree, d, True)
    return d


def gates_cfg(tc, today, until, section="ask_gate"):
    path = None
    if until is not None:
        path = os.path.join(tmpdir(tc), "gates.json")
        json.dump({section: {"observe_until": until}}, open(path, "w"))
    with mock.patch.object(G, "config_path", return_value=path), mock.patch.object(G, "warn"), mock.patch.object(D, "today", return_value=today), \
            mock.patch.dict(os.environ, {"HARNESS_HOME": tmpdir(tc)}):
        G.load_config(section)
        return dict(G.CFG)


def r_shipped_defaults(tc):
    tc.assertEqual((G.DEFAULTS["observe_until"], G.HARNESS_DEFAULTS["observe_until"], idcheck.OBSERVE_UNTIL), ("", "", ""))
    tc.assertEqual(json.load(open(os.path.join(ROOT, "data", "role-aliases.json")))["until"], "")
    with mock.patch.object(D, "today", return_value=FROZEN):                              # behaviour equals 0.27.1 on the release day: all three ended
        for sec in ("ask_gate", "harness"):
            c = gates_cfg(tc, FROZEN, None, sec)
            tc.assertEqual((c["enabled"], c["ended"]), (False, True))
        tc.assertTrue(idcheck.expired())
        with mock.patch.object(H, "_ROLE_ALIASES", ({"corpus-envoy": "envoy"}, "")), mock.patch.object(H, "alias_today", return_value=FROZEN):
            with tc.assertRaisesRegex(H.HarnessError, "renamed to 'envoy'"):
                H.cr_input("corpus-envoy")
    c = gates_cfg(tc, FROZEN, "2026-12-06")                                              # his renewal in config still switches it on
    tc.assertTrue(c["enabled"])
    src = open(os.path.join(ROOT, "scripts", "harness.py"), encoding="utf-8").read()
    tc.assertIn('load_config(h.home).get("idcheck_observe_until")', src)                  # the config read is kept


def r_scan_literals(tc):
    with mock.patch.object(D, "today", return_value=FROZEN):
        late = [h for h in D.scan_literals(ROOT) if h[3] > D.today()]
    tc.assertEqual(late, [], "a date later than today in shipped code or data (file, line, name, date): %s" % late)
    tc.assertEqual(D.scan_literals(ROOT), [], "shipped code and data carry no switch date at all")
    d = tmpdir(tc)
    os.makedirs(os.path.join(d, "scripts"))
    os.makedirs(os.path.join(d, "data"))
    open(os.path.join(d, "scripts", "x.py"), "w").write('A = 1\nOBSERVE_UNTIL = "2099-01-01"\nd = {"observe_until": "2099-02-02"}\n')
    open(os.path.join(d, "data", "t.json"), "w").write('{\n "until": "2099-03-03"\n}\n')
    got = sorted((os.path.basename(p), n, name, v) for p, n, name, v in D.scan_literals(d))
    tc.assertEqual(got, [("t.json", 2, "until", "2099-03-03"), ("x.py", 2, "OBSERVE_UNTIL", "2099-01-01"), ("x.py", 3, "observe_until", "2099-02-02")])


def r_injected_clock(tc):
    for until, today, on in (("2026-12-06", "2026-12-05", True), ("2026-12-06", "2026-12-06", True), ("2026-12-06", "2026-12-07", False), ("", "2026-12-06", False),
                             (None, "2026-12-06", False), ("2026-13-45", "2026-12-06", False), ("soon", "2026-12-06", False)):
        tc.assertEqual(D.is_on(until, today, home=tmpdir(tc)), on, (until, today))
        tc.assertEqual(gates_cfg(tc, today, until, "harness")["enabled"], on, ("ask_gate", until, today))
        with mock.patch.object(D, "today", return_value=today):
            tc.assertEqual(not idcheck.expired(until or None), on, ("idcheck", until, today))
        with mock.patch.object(H, "_ROLE_ALIASES", ({"corpus-envoy": "envoy"}, until or "")), mock.patch.object(H, "alias_today", return_value=today), \
                mock.patch.dict(os.environ, {"HARNESS_HOME": tmpdir(tc)}):
            try:
                H.cr_input("corpus-envoy")
                accepted = True
            except H.HarnessError:
                accepted = False
            tc.assertEqual(accepted, on, ("alias", until, today))
    src = open(os.path.join(ROOT, "scripts", "harness.py"), encoding="utf-8").read()       # harness.alias_today kept and delegating (the test runner pins the name itself)
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "alias_today")
    ns = {"time": time}
    exec(ast.get_source_segment(src, fn), ns)
    with mock.patch.object(D, "today", return_value="2031-01-02"):
        tc.assertEqual(ns["alias_today"](), "2031-01-02")


def r_callers_use_the_module_and_malformed_warns_once(tc):
    for f in ("ask_gate.py", "idcheck.py", "harness.py"):
        src = open(os.path.join(ROOT, "scripts", f), encoding="utf-8").read()
        tc.assertNotRegex(src, r"from\s+dated_switches\s+import", f)
        tc.assertIn("dated_switches.", src, f)
    home = tmpdir(tc)
    os.makedirs(os.path.join(home, "_harness"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        for _ in range(3):
            tc.assertFalse(D.is_on("2026-99-99", "2026-12-01", "x_until", home))
    tc.assertEqual(out.getvalue(), "")
    lines = open(os.path.join(home, "_harness", "dated_switches.log")).read().splitlines()
    tc.assertEqual(len(lines), 1)
    tc.assertIn("x_until", lines[0])
    tc.assertFalse(D.is_on("2026-99-99", "2026-12-01", "x_until", os.path.join(home, "absent")))     # no home: silent


def _days(n):
    import datetime
    return (datetime.date.fromisoformat(D.today()) + datetime.timedelta(days=n)).isoformat()


def _home_with(tc, **cfg):
    home = tmpdir(tc)
    os.makedirs(os.path.join(home, "_harness"))
    json.dump(cfg, open(os.path.join(home, "_harness", "config.json"), "w"))
    return home


def r_check_cli(tc):
    for cfg, want in (({"idcheck_observe_until": _days(10)}, 1), ({"idcheck_observe_until": _days(14)}, 1), ({"idcheck_observe_until": _days(20)}, 0),
                      ({"idcheck_observe_until": _days(-3)}, 1), ({"idcheck_observe_until": _days(10), "other_until": _days(5)}, 2), ({"unrelated": _days(1)}, 0)):
        home = _home_with(tc, **cfg)
        with mock.patch.dict(os.environ, {"GATES_CONFIG": os.path.join(home, "none.json")}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = D.main(["check", "--home", home])
        tc.assertEqual((rc, len(out.getvalue().splitlines())), (0, want), cfg)
    home = _home_with(tc, idcheck_observe_until=_days(5))
    p = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "scripts", "dated_switches.py"), "check"], capture_output=True, text=True,
                       env={"PATH": "/usr/bin", "HARNESS_HOME": home, "HOME": home, "GATES_CONFIG": os.path.join(home, "none.json")})
    tc.assertEqual((p.returncode, len(p.stdout.splitlines()), p.stderr), (0, 1, ""))
    gp = os.path.join(home, "gates.json")                                                  # gates.json sections are scanned too
    json.dump({"harness": {"observe_until": _days(3)}, "ask_gate": {"observe_until": _days(60)}}, open(gp, "w"))
    tc.assertEqual(len(D.warnings(home, gates_path=gp)), 2)


def r_sync_do_line(tc):
    for days, want in ((10, True), (20, False)):
        tmp = tmpdir(tc)
        with mock.patch.dict(os.environ, {"HARNESS_CACHE": os.path.join(tmp, "cache"), "GATES_CONFIG": os.path.join(tmp, "none.json")}):
            h = H.Harness(os.path.join(tmp, "home"))
            a = h.register(project="orchestration", model="claude-sonnet-5-5")["id"]
            os.makedirs(os.path.join(tmp, "home", "_harness"), exist_ok=True)
            json.dump({"idcheck_observe_until": _days(days)}, open(os.path.join(tmp, "home", "_harness", "config.json"), "w"))
            text = h.sync(a)["text"]
        tc.assertEqual("dated switch idcheck_observe_until" in text, want, (days, text))


def r_clock_boundary(tc):
    old = os.environ.get("TZ")
    tc.addCleanup(lambda: (os.environ.__setitem__("TZ", old) if old else os.environ.pop("TZ", None), time.tzset()))
    for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago", "UTC"):                          # the local date, not the UTC date, in the extremes
        os.environ["TZ"] = tz
        time.tzset()
        tc.assertEqual(D.today(), time.strftime("%Y-%m-%d"), tz)
    tc.assertNotRegex(open(os.path.join(ROOT, "scripts", "dated_switches.py"), encoding="utf-8").read(), r"utcnow|timezone|gmtime")
    tc.assertTrue(D.is_on("2026-11-24", "2026-11-24"))                                       # 23:59 on the date: on
    tc.assertFalse(D.is_on("2026-11-24", "2026-11-25"))                                      # 00:00 the next day: off
    d = tmpdir(tc)                                                                           # a missing config file (not only a missing key) is the ended state
    tc.assertEqual(D.scan(d, gates_path=os.path.join(d, "absent.json")), [])
    tc.assertEqual(D.warnings(d, gates_path=os.path.join(d, "absent.json")), [])
    c = gates_cfg(tc, FROZEN, None)
    tc.assertEqual((c["enabled"], c["ended"]), (False, True))


ROWS = {"I3-01": r_shipped_defaults, "I3-02": r_scan_literals, "I3-03": r_injected_clock, "I3-04": r_callers_use_the_module_and_malformed_warns_once,
        "I3-05": r_check_cli, "I3-06": r_sync_do_line, "I3-07": r_clock_boundary}
