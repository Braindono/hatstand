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

    # ---- 0.21.1 (A-58ff8 item 5): the mirror archives only files a PREVIOUS publish copied (_harness/data/.mirrored.json)
    LOCAL = {"ontology-mapping.json": "{}", "lesson_cues.json": "{}", "my.local.json": "{}", "hatstand-private-terms.txt": "x\n", "notes.md": "n\n"}

    def put_local(self):
        d = os.path.join(self.hd, "data")
        os.makedirs(d, exist_ok=True)
        for n, t in self.LOCAL.items():
            with open(os.path.join(d, n), "w") as f:
                f.write(t)
        return d

    def test_local_files_survive_every_publish(self):
        d = self.put_local()
        for _ in range(3):
            r = self.h._mirror_launcher(ROOT)
            self.assertNotIn("data_archived", r)
        for n in self.LOCAL:
            self.assertTrue(os.path.isfile(os.path.join(d, n)), n)
        self.assertFalse(os.path.exists(os.path.join(d, "_archive")))

    def test_first_publish_with_no_manifest_archives_nothing(self):
        d = os.path.join(self.hd, "data")
        os.makedirs(d)
        with open(os.path.join(d, "old-table.json"), "w") as f:
            f.write("{}")
        r = self.h._mirror_launcher(ROOT)
        self.assertNotIn("data_archived", r)
        self.assertTrue(os.path.isfile(os.path.join(d, "old-table.json")))

    def test_a_file_the_last_publish_copied_and_the_package_dropped_is_archived_not_deleted(self):
        d = os.path.join(self.hd, "data")
        os.makedirs(d)
        with open(os.path.join(d, "old-table.json"), "w") as f:
            f.write('{"a": 1}')
        with open(os.path.join(d, ".mirrored.json"), "w") as f:
            json.dump({"files": ["old-table.json", "role-aliases.json"]}, f)           # the previous publish copied it
        self.put_local()
        r = self.h._mirror_launcher(ROOT)
        self.assertEqual(r.get("data_archived"), 1)
        self.assertFalse(os.path.exists(os.path.join(d, "old-table.json")))
        with open(os.path.join(d, "_archive", "old-table.json")) as f:
            self.assertEqual(f.read(), '{"a": 1}')                                         # archived intact, never deleted
        for n in self.LOCAL:
            self.assertTrue(os.path.isfile(os.path.join(d, n)), n)

    def test_the_manifest_is_rewritten_each_publish_and_is_never_archived(self):
        r1 = self.h._mirror_launcher(ROOT)
        mf = os.path.join(self.hd, "data", ".mirrored.json")
        with open(mf) as f:
            m1 = json.load(f)["files"]
        self.assertEqual(len(m1), r1["data"])
        self.assertEqual(sorted(m1), sorted(x for x in os.listdir(os.path.join(ROOT, "data")) if x.endswith((".json", ".md"))))
        with open(mf, "w") as f:
            json.dump({"files": ["gone.json"]}, f)
        self.h._mirror_launcher(ROOT)
        with open(mf) as f:
            self.assertEqual(json.load(f)["files"], m1)
        self.assertTrue(os.path.isfile(mf))
        self.assertFalse(os.path.exists(os.path.join(self.hd, "data", "_archive", ".mirrored.json")))

    def test_a_byte_mismatch_still_fails_the_publish(self):
        from unittest import mock
        with mock.patch("filecmp.cmp", return_value=False):
            with self.assertRaises(H.HarnessError):
                self.h._mirror_launcher(ROOT)

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
