"""Test hermeticity (cc 0.15.6 review item): importing this module points HOME and the harness state at a private
temp tree and clears every HARNESS_* variable, so no test can read or write the host's ~/.claude, ~/Claude or the
live Exchange. Each test file imports it first. A test that needs its own variable sets it after the import."""
import atexit, os, shutil, tempfile

if not os.environ.get("CC_TEST_ISOLATED"):
    _root = tempfile.mkdtemp(prefix="cc-tests-")
    for _k in [k for k in os.environ if k.startswith("HARNESS_")]:
        del os.environ[_k]
    os.environ["HOME"] = _root
    os.environ["HARNESS_STATE_DIR"] = os.path.join(_root, "state")
    os.environ["CC_TEST_ISOLATED"] = _root
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # 0.16.1 item 8: the release-scope gate is on in production; the existing publish tests run with it switched off in the
    # private operator.json of the test HOME. tests/test_cc161_scope_gate.py switches it on for its own cases.
    _cfg = os.path.join(_root, ".config", "crew-coordinator")
    os.makedirs(_cfg, exist_ok=True)
    with open(os.path.join(_cfg, "operator.json"), "w") as _f:
        _f.write('{"release_scope_gate": false}')
    os.chmod(os.path.join(_cfg, "operator.json"), 0o600)
    atexit.register(shutil.rmtree, _root, True)

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
    ev = os.path.join(home, "_harness", "events.jsonl")
    if not os.path.exists(ev):
        open(ev, "a").close()
