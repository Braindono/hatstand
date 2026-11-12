"""cc 0.24.0 item 15 (scope A-b2950; hatstand history scan 2026-11-10, step A, curator m-e831d9d09013): no identity in the plugin
sources. A self-check over every text file of this tree: no user name in a /Users, /home or C:\\Users path (synthetic x, bob, claude
and <name> placeholders allowed), no host name of the operator's machines or of this machine, no real cross-session message id, and no
email outside the test domains and the noreply sync identity. The identity values are kept as sha256 of the lower-cased token, never as
text, so this file cannot re-add them. No string is exempt. Since the 0.24.0 release tree, the curator's scrubbed CHANGELOG.md is scanned too.
Fails on 0.23.0 (host names in harness.py and the tests, a real uuid, a home path).
Run: python3 -B tests/test_c240_item15.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import hashlib, os, re, socket, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_FILES = set()                                  # the CHANGELOG is scanned since its 0.24.0 scrub
SKIP_DIRS = {"__pycache__", ".git", ".claude"}
# sha256 of lower-cased tokens: the two host names the operator's Mac has reported (scan finding 4) and the real message uuid (finding 6)
IDENTITY_SHA = {"5d47ec79f3b591160d8d1831da812551cbcccd0c2bc771129902c1bdbce19568",
                "a5a62bf072ce20efe3791ebb415dcd6b672381e9efb9587da93e1e942a37aa1e",
                "27daf085e228869d28cd1af2d57b46d60e5c5844a7cbf6270e7b6fd24da3dc8a"}
ALLOWED_USERS = {"x", "bob", "claude", "<name>", "<user>", "<you>"}
# the operator's user name as a word anywhere (sha256 of the lower-cased word), and the current machine's user at test time
USER_SHA = {"3ca0fdf06e7ffb5cfadfbe01505f6555595ae7abb78843bad2f1a128b4617741"}
_WORD = re.compile(r"[A-Za-z0-9]+")
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "example.invalid", ".test", "users.noreply.github.com")
_HOME = re.compile(r"(?:/Users/|/home/|C:\\\\Users\\\\|C:\\Users\\)([A-Za-z0-9_.<>-]+)")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{3,63}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _sha(s):
    return hashlib.sha256(s.lower().encode("utf-8")).hexdigest()


def text_files():
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), ROOT)
            if rel in SKIP_FILES:
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    yield rel, fh.read()
            except (UnicodeDecodeError, OSError):
                continue


def scan():
    import getpass
    host = socket.gethostname().split(".")[0]
    ident = set(IDENTITY_SHA) | ({_sha(host)} if len(host) >= 4 and host.lower() != "localhost" else set())
    try:
        me = getpass.getuser()
    except Exception:
        me = ""
    users = set(USER_SHA) | ({_sha(me)} if me and me.lower() not in ALLOWED_USERS | {"root", "runner", "user"} else set())
    out = []
    for rel, txt in text_files():
        for n, line in enumerate(txt.splitlines(), 1):
            if any(_sha(w) in users for w in _WORD.findall(line)):
                out.append((rel, n, "user name"))
            for m in _HOME.finditer(line):
                if m.group(1) not in ALLOWED_USERS:
                    out.append((rel, n, "home path with a user name"))
            if any(_sha(t) in ident for t in _TOKEN.findall(line)):
                out.append((rel, n, "host name or real message id"))
            for m in _EMAIL.finditer(line):
                if not m.group(1).lower().endswith(ALLOWED_EMAIL_DOMAINS):
                    out.append((rel, n, "email outside the test domains"))
    return out


class Item15(unittest.TestCase):
    def test_no_identity_in_the_plugin_tree(self):
        found = scan()
        self.assertEqual(found, [], "\n".join("%s:%d %s" % f for f in found[:20]))

    def test_the_check_catches_each_kind(self):
        tokens = ("/Users/" + "someone/Claude", "C:\\Users\\" + "someone\\x", "a@" + "gmail.com")   # built in pieces: no self-match
        for t in tokens:
            with self.subTest(t=t):
                self.assertTrue(_HOME.search(t) and _HOME.search(t).group(1) not in ALLOWED_USERS or
                                (_EMAIL.search(t) and not _EMAIL.search(t).group(1).endswith(ALLOWED_EMAIL_DOMAINS)))
        for ok in ("/Users/x/Claude", "/home/bob/x", "/Users/<name>/x", "t@example.invalid", "Braindono@users.noreply.github.com"):
            with self.subTest(ok=ok):
                h, e = _HOME.search(ok), _EMAIL.search(ok)
                self.assertFalse((h and h.group(1) not in ALLOWED_USERS) or (e and not e.group(1).endswith(ALLOWED_EMAIL_DOMAINS)))

    # envoy m-87cdc272127b: the intake folder is renamed, an old <name>_skills_repository folder stays in use, no exception here
    def test_the_intake_default_is_neutral_and_an_old_folder_stays_in_use(self):
        import shutil, tempfile
        sys_path = os.path.join(ROOT, "scripts")
        import sys
        sys.path.insert(0, sys_path)
        import insight_share as I
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.assertEqual(I.intake_path(home), os.path.join(home, "skills_repository", "INTAKE.md"))
        os.makedirs(os.path.join(home, "old_skills_repository"))
        self.assertEqual(I.intake_path(home), os.path.join(home, "old_skills_repository", "INTAKE.md"))   # nothing moves
        I.intake_append(home, "me", "a note")
        self.assertIn("a note", open(os.path.join(home, "old_skills_repository", "INTAKE.md")).read())
        os.makedirs(os.path.join(home, "skills_repository"))
        self.assertEqual(I.intake_path(home), os.path.join(home, "skills_repository", "INTAKE.md"))       # the new one wins
        os.makedirs(os.path.join(home, "other_skills_repository"))
        os.rmdir(os.path.join(home, "skills_repository"))
        self.assertEqual(I.intake_path(home), os.path.join(home, "skills_repository", "INTAKE.md"))       # two old ones: no guess

    def test_identity_tokens_are_stored_hashed(self):
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", x) for x in IDENTITY_SHA))
        self.assertEqual(_sha("Host-A"), _sha("host-a"))                           # case-insensitive


if __name__ == "__main__":
    unittest.main()
