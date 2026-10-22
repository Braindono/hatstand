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
    atexit.register(shutil.rmtree, _root, True)

REAL_HOME_UNTOUCHED = os.environ["HOME"] == os.environ.get("CC_TEST_ISOLATED")
