"""cc 0.25.0 item 33: Harness home guard. Only an omitted argument falls back to the default home; "" and None raise and never open the real ledger;
an existing non-folder raises; a missing path stays valid. Run: python3 -B tests/test_c250_item33.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, tempfile, unittest
from unittest import mock

import test_c220_nudge as C
from test_c220_nudge import H


class Item33(unittest.TestCase):
    def test_empty_string_and_none_raise_and_never_open_a_ledger(self):
        with mock.patch.object(H, "FileStore", side_effect=AssertionError("opened a store")), mock.patch.object(H, "resolve_home", side_effect=AssertionError("fell back")):
            for bad in ("", None):
                with self.subTest(home=bad), self.assertRaisesRegex(H.HarnessError, "home must be a path"):
                    H.Harness(bad)

    def test_a_path_like_home_is_stored_as_a_string(self):
        import pathlib
        d = tempfile.mkdtemp()
        h = H.Harness(pathlib.Path(d))
        self.assertIsInstance(h.home, str)
        self.assertEqual(h.home, d)

    def test_a_file_where_a_home_should_be_raises(self):
        f = tempfile.NamedTemporaryFile(delete=False)
        f.close()
        self.addCleanup(os.unlink, f.name)
        with self.assertRaisesRegex(H.HarnessError, "not a folder"):
            H.Harness(f.name)

    def test_a_missing_path_and_an_existing_folder_work_and_omitted_uses_the_default(self):
        d = tempfile.mkdtemp()
        self.assertEqual(H.Harness(d).home, d)
        missing = os.path.join(d, "not", "yet")
        self.assertEqual(H.Harness(missing).home, missing)
        with mock.patch.object(H, "resolve_home", return_value=d):
            self.assertEqual(H.Harness().home, d)

    def test_every_explicit_caller_in_scripts_passes_a_value_that_is_never_empty(self):
        """The commit's list: harness.py 9039/9399, hatstand_check.py, mcp_server.py call Harness() (omitted); live_metrics.py, release_guard.py and
        sim_launcher.py (x2) pass a home taken from their arguments, which their own argument parsing requires."""
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
        explicit = {}
        for fn in sorted(os.listdir(here)):
            if fn.endswith(".py"):
                for i, ln in enumerate(open(os.path.join(here, fn), encoding="utf-8"), 1):
                    if "Harness(" in ln and "class Harness" not in ln and ("Harness()" not in ln) and not ln.lstrip().startswith(("#", '"""')):
                        explicit.setdefault(fn, []).append(ln.strip()[:60])
        self.assertEqual(sorted(explicit), ["live_metrics.py", "release_guard.py", "sim_launcher.py"], explicit)


if __name__ == "__main__":
    unittest.main()
