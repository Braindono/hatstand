"""Test hermeticity (cc 0.15.6 review item): importing this module points HOME and the harness state at a private
temp tree and clears every HARNESS_* variable, so no test can read or write the host's ~/.claude, the <workspace> folder or the
live Exchange. Each test file imports it first. A test that needs its own variable sets it after the import."""
import atexit, os, shutil, tempfile

if not os.environ.get("CC_TEST_ISOLATED"):
    _root = tempfile.mkdtemp(prefix="cc-tests-")
    for _k in [k for k in os.environ if k.startswith("HARNESS_")]:
        del os.environ[_k]
    os.environ.pop("CLAUDE_CODE_HOST_SESSION_ID", None)   # 0.22.0: the runner's own chat id must never become a test agent's address
    os.environ["HOME"] = _root
    os.environ["HARNESS_STATE_DIR"] = os.path.join(_root, "state")
    os.environ["CC_TEST_ISOLATED"] = _root
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"       # 0.24.0 item 17: no test reads the machine's system git config
    # 0.16.1 item 8: the release-scope gate is on in production; the existing publish tests run with it switched off in the
    # private operator.json of the test HOME. tests/test_cc161_scope_gate.py switches it on for its own cases.
    _cfg = os.path.join(_root, ".config", "crew-coordinator")
    os.makedirs(_cfg, exist_ok=True)
    with open(os.path.join(_cfg, "operator.json"), "w") as _f:
        _f.write('{"release_scope_gate": false}')
    os.chmod(os.path.join(_cfg, "operator.json"), 0o600)
    atexit.register(shutil.rmtree, _root, True)

# 0.26.2: the signed-operator gate reads root files at fixed paths; on a machine where the seat is installed that would switch the gate on
# inside every test. In-process tests get the root-log paths moved to a private empty folder (the operator tests move them again).
if os.environ.get("CC_TEST_ISOLATED") and "operator_sign" not in __import__("sys").modules:
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
    import operator_sign as _OS
    _none = os.path.join(os.environ["CC_TEST_ISOLATED"], "no-root")
    _OS.LOG, _OS.PUB, _OS.FLAG = (os.path.join(_none, "log"), os.path.join(_none, "pub"), os.path.join(_none, "off"))

REAL_HOME_UNTOUCHED = os.environ["HOME"] == os.environ.get("CC_TEST_ISOLATED")


def guard_home(home):
    """0.21.0 (A-5a989 item 9): hatstand_guard fails closed unless the home has a readable ledger and a private-terms list. Tests that
    run the Hatstand sync or the guard give their home both, with one SYNTHETIC term that no test text uses."""
    d = os.path.join(home, "_harness", "data")
    os.makedirs(d, exist_ok=True)
    t = os.path.join(d, "hatstand-private-terms.txt")
    if not os.path.exists(t):
        with open(t, "w") as f:
            f.write("# synthetic, for tests\nzzz-synthetic-private-term\n")
    ident = os.path.join(d, "hatstand-private-identity.txt")       # 0.24.0 item 17: the identity list, synthetic values
    if not os.path.exists(ident):
        with open(ident, "w") as f:
            f.write("# synthetic, for tests\nuser zzsynthuser\nhost zzsynthhost\nemail zz@identity.example.invalid\n")
    ev = os.path.join(home, "_harness", "events.jsonl")
    if not os.path.exists(ev):
        open(ev, "a").close()


HATSTAND_INCLUDE_PATTERNS = ("**/[Hh]atstand", "**/[Hh]atstand.git", "**/[Hh]atstand.git/", "**/[Hh]atstand/")


def hatstand_hooks(tmp, home, gitconfig):
    """0.24.0 item 17: install the Hatstand hooks into <tmp>/hooks-hatstand for this home and switch them on in the scratch
    global git config (GIT_CONFIG_GLOBAL) with the four includeIf lines, as the operator does once per machine. -> the folder."""
    import subprocess, sys
    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    dest = os.path.join(tmp, "hooks-hatstand")
    guard_home(home)
    subprocess.run([sys.executable, "-I", "-B", os.path.join(scripts, "hatstand_check.py"), "install", dest, "--home", home],
                   check=True, capture_output=True)
    with open(gitconfig, "a") as f:
        for p in HATSTAND_INCLUDE_PATTERNS:
            f.write('[includeIf "hasconfig:remote.*.url:%s"]\n\tpath = %s\n' % (p, os.path.join(dest, "gitconfig")))
    return dest
