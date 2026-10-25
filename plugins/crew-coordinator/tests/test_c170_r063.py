"""cc 0.17.0 R-063 (plugin half): the Exchange launcher mirror carries data/ (role and project aliases, word lists), so
the CLI copy in _harness/bin resolves the old role names. Run: python3 -B tests/test_c170_r063.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import harness as H


class Mirror(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "Exchange")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.hd = self.h.store.dir

    def test_scripts_and_data_are_mirrored(self):
        r = self.h._mirror_launcher(ROOT)
        py = sorted(f for f in os.listdir(os.path.join(ROOT, "scripts")) if f.endswith(".py"))
        dat = sorted(f for f in os.listdir(os.path.join(ROOT, "data")) if f.endswith((".json", ".md")))
        self.assertEqual((r["bin"], r["data"]), (len(py), len(dat)))
        self.assertIn("role-aliases.json", os.listdir(os.path.join(self.hd, "data")))
        self.assertIn("nouns.md", os.listdir(os.path.join(self.hd, "data")))

    def test_stale_data_file_is_archived_not_deleted(self):
        os.makedirs(os.path.join(self.hd, "data"))
        with open(os.path.join(self.hd, "data", "old-table.json"), "w") as f:
            f.write("{}")
        r = self.h._mirror_launcher(ROOT)
        self.assertEqual(r.get("data_archived"), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.hd, "data", "_archive", "old-table.json")))

    def test_bin_copy_resolves_old_role_names(self):
        self.h._mirror_launcher(ROOT)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import harness as H, json; "
                "t, until = H.role_alias_table(); print(json.dumps({'envoy': t.get('corpus-envoy'), 'root': H.PLUGIN_ROOT}))")
        out = subprocess.run([sys.executable, "-B", "-c", code, os.path.join(self.hd, "bin")], env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        d = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(os.path.realpath(d["root"]), os.path.realpath(self.hd))
        self.assertEqual(d["envoy"], "envoy")

    def test_plugin_without_data_folder_mirrors_scripts_only(self):
        fake = tempfile.mkdtemp()
        shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(fake, "scripts"))
        r = self.h._mirror_launcher(fake)
        self.assertIn("bin", r)
        self.assertNotIn("data", r)


if __name__ == "__main__":
    unittest.main()
