"""Operator seat stage 1: agents cannot hold the seat; "*" skips the seat; model warning at register/restore.
Run: python3 -B tests/test_operator_seat.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import seat_guard as SG
import restore_model_warn as RMW

SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-5-5"


class SeatGuard(unittest.TestCase):
    def setUp(self):
        self.home = os.path.join(tempfile.mkdtemp(), "home")
        os.makedirs(self.home)
        self.h = H.Harness(self.home)
        self.h.role_define("operator", "operator", "claude", carry="full")      # the seat exists, as on the live ledger
        self.h.role_define("operator", "envoy", "harness-ops")

    def test_register_as_operator_refused(self):
        with self.assertRaises(H.HarnessError) as c:
            self.h.register(project="claude", model=SONNET, role="operator")
        self.assertIn("his alone", str(c.exception))

    def test_task_named_operator_refused(self):
        with self.assertRaises(H.HarnessError):
            self.h.register(project="claude", model=SONNET, task="operator")

    def test_restore_as_operator_refused_and_writes_nothing(self):
        n = len(list(self.h.store.events()) if hasattr(self.h.store, "events") else [])
        with self.assertRaises(H.HarnessError):
            self.h.restore("operator", model=HAIKU, confirmed=True)
        if hasattr(self.h.store, "events"):
            self.assertEqual(n, len(list(self.h.store.events())))

    def test_successor_of_seat_holder_refused(self):
        self.h._seat_allowed = True            # the future signed CLI path installs the holder
        a = self.h.register(project="claude", model=SONNET, role="operator")["id"]
        self.h._seat_allowed = False
        with self.assertRaises(H.HarnessError):
            self.h.register(project="claude", model=SONNET, predecessor=a)

    def test_other_roles_unaffected(self):
        c = self.h.register(project="harness-ops", model=SONNET, role="envoy")
        self.assertTrue(c["id"])

    def test_broadcast_skips_seat_holder_but_direct_mail_arrives(self):
        self.h._seat_allowed = True
        seat = self.h.register(project="claude", model=SONNET, role="operator")["id"]
        self.h._seat_allowed = False
        other = self.h.register(project="harness-ops", model=SONNET, role="envoy")["id"]
        self.h.send(other, "*", "to everyone", subject="b")
        self.h.send(other, "role:operator", "to the seat", subject="d")
        got = [m for m in self.h._inbox_ids(self.h.state(), seat)]
        subjects = [self.h.state().messages[i].get("subject") for i in got]
        self.assertNotIn("b", subjects)
        self.assertIn("d", subjects)

    def test_helpers(self):
        self.assertTrue(SG.is_seat(" Operator "))
        self.assertFalse(SG.is_seat("envoy"))
        SG.refuse_if_seat("envoy", None, None)
        with self.assertRaises(ValueError):
            SG.refuse_if_seat(None, "operator", None)
        SG.refuse_if_seat("operator", holder_ok=True)


class ModelWarn(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        d = os.path.join(self.root, "projects", "orchestration", "scripts", "rules")
        os.makedirs(d)
        json.dump({"aliases": {"sonnet": SONNET, "haiku": HAIKU, "fable": "claude-fable-5-2"},
                   "roles": {"envoy": ["claude-fable-5-2"], "steward": [HAIKU, SONNET]}},
                  open(os.path.join(d, "role_models.json"), "w"))
        os.environ["HARNESS_OPS_ROOT"] = self.root

    def tearDown(self):
        os.environ.pop("HARNESS_OPS_ROOT", None)

    def test_mismatch_warns_with_alias(self):
        s = RMW.model_line("envoy", SONNET)
        self.assertIn(SONNET, s)
        self.assertIn("/model fable", s)

    def test_match_unlisted_unknown_silent(self):
        self.assertEqual(RMW.model_line("envoy", "claude-fable-5-2"), "")
        self.assertEqual(RMW.model_line("steward", SONNET), "")
        self.assertEqual(RMW.model_line("curator", SONNET), "")
        self.assertEqual(RMW.model_line("envoy", "unknown"), "")

    def test_missing_file_silent(self):
        os.environ["HARNESS_OPS_ROOT"] = os.path.join(self.root, "none")
        self.assertEqual(RMW.model_line("envoy", SONNET), "")

    def test_banner_first_line_on_register(self):
        home = os.path.join(self.root, "home")
        os.makedirs(home)
        h = H.Harness(home)
        h.role_define("operator", "envoy", "harness-ops")
        c = h.register(project="harness-ops", model=SONNET, role="envoy")
        self.assertTrue(c["banner"].startswith("Model: this chat runs"))
        self.assertEqual(c["short"], c["short"])


class SudoersDropIn(unittest.TestCase):
    """0.26.2: the setup script installs one sudoers drop-in (!use_pty for the signer only), validated first, refusing cleanly. Text-level tests:
    visudo and root are not run here (his install run is the live proof)."""
    @classmethod
    def setUpClass(cls):
        import seat_setup as SS
        cls.SS, cls.text = SS, SS.build("/tmp/x-home", 501)

    def test_exactly_one_line_and_it_passes_the_scripts_own_refusal_greps(self):
        import re
        self.assertEqual(self.SS.SUDOERS_LINE, "Defaults!/usr/local/libexec/harness-grant !use_pty")
        self.assertIsNone(re.search(r"NOPASSWD|!authenticate|!tty_tickets|timestamp_type *= *global|timestamp_timeout *= *(-|[6-9]|[1-9][0-9])", self.SS.SUDOERS_LINE))

    def test_validated_before_install_and_nothing_installed_before_the_checks(self):
        t = self.text
        i_inc, i_visudo, i_files, i_drop = (t.index(k) for k in ("includedir", "visudo -cf", "/usr/bin/install -d -m 0755", "install -m 0440 -o root -g wheel"))
        self.assertLess(i_inc, i_visudo); self.assertLess(i_visudo, i_files); self.assertLess(i_visudo, i_drop)
        self.assertIn("nothing was installed", t)
        self.assertIn("-m 0440 -o root -g wheel", t)
        self.assertLess(t.index("/etc/sudoers.d is missing"), i_visudo)

    def test_header_has_the_undo_and_the_line_and_sha_are_printed(self):
        head = "\n".join(self.text.splitlines()[:6])
        self.assertIn("sudo rm /etc/sudoers.d/harness-grant", head)
        self.assertIn("shasum -a 256 harness-grant.sudoers", self.text)

    def test_script_is_valid_bash_and_no_other_sudoers_content(self):
        import subprocess, tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(self.text)
        try:
            self.assertEqual(subprocess.run(["/bin/bash", "-n", f.name], capture_output=True).returncode, 0)
        finally:
            os.unlink(f.name)
        self.assertEqual(self.text.count("Defaults!"), 1)


if __name__ == "__main__":
    unittest.main()
