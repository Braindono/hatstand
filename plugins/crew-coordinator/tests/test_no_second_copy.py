"""0.27.2 (foresight pass): a pre-check keeps no second copy of what its checker defines. Fails when scripts/ holds a second literal copy of SCOPE_GATE_RE's pattern, of release_sim's
GATE_FILES tuple, or of the mechanical-prune classifier (a capsule or note whose author is done), beyond the one definition of each.
Run: python3 -B -m unittest tests.test_no_second_copy   Depends on: scripts/*.py (read as text and by ast), scripts/release_sim.py."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401
import ast, glob, os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import release_sim as RS

GATE_RE_PATTERN = r"gate files? changed:\s*([A-Za-z0-9_./:, -]+)"
CLASSIFIER_RE = re.compile(r"""["']kind["']\]\s+in\s+\(\s*["']capsule["']\s*,\s*["']note["']\s*\)\s+and\s+\w+\[["']agent["']\]""")   # kind in (capsule, note) and its author is done


def sources():
    return {os.path.basename(p): open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(SCRIPTS, "*.py")))}


class NoSecondCopy(unittest.TestCase):
    def test_scope_gate_regex_pattern_defined_once(self):
        hits = [(f, n) for f, s in sources().items() for n, line in enumerate(s.splitlines(), 1) if "gate files? changed" in line.lower() and "re.compile" in line]
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0][0], "harness.py")
        self.assertEqual(sum(s.count(GATE_RE_PATTERN) for s in sources().values()), 1)

    def test_gate_files_tuple_defined_once_and_nobody_copies_it(self):
        """A tuple or list literal holding four or more of the simulator's gate file names is a copy; harness.Harness.GATE_FILES (three names, the older 0.22.5 check's own
        set, not a copy of the simulator's) stays below the line."""
        names = set(RS.GATE_FILES)
        copies = []
        for f, s in sources().items():
            for node in ast.walk(ast.parse(s)):
                if isinstance(node, (ast.Tuple, ast.List)):
                    got = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                    if len(got & names) >= 4:
                        copies.append((f, node.lineno))
        self.assertEqual(copies, [("release_sim.py", next(n.lineno for n in ast.walk(ast.parse(sources()["release_sim.py"])) if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "GATE_FILES" for t in n.targets)))])

    def test_mechanical_classifier_defined_once(self):
        hits = [(f, n) for f, s in sources().items() for n, line in enumerate(s.splitlines(), 1) if CLASSIFIER_RE.search(line)]
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0][0], "harness.py")

    def test_the_scanner_finds_a_planted_copy(self):
        planted = 'GATE_FILES = ("scripts/release_sim.py", "scripts/sim_launcher.py", "tests/sim_invariants_critic.py", "hooks/hooks.json")\n'
        node = ast.parse(planted).body[0].value
        got = {e.value for e in node.elts} & set(RS.GATE_FILES)
        self.assertGreaterEqual(len(got), 4)
        self.assertTrue(CLASSIFIER_RE.search('mech = lambda r: r["kind"] in ("capsule", "note") and r["agent"]'))


if __name__ == "__main__":
    unittest.main()
