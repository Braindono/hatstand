"""cc 0.22.4 (scope A-003cf): the release simulator's two blind spots. R1 regression on the real 0.22.1 -> 0.22.2 doorbell.py diff,
R2 continuation line of a Do: string, R3 new field on an existing event type, R4 no question storm on 0.22.3 vs 0.22.2.
Only the question generator runs here (no child run), so each test is fast. Run: python3 -B tests/test_c224_sim.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import importlib.util, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPECS = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import release_sim as RS

R4_BOUND = 40       # recorded count is in the build report; the bound only stops a storm


def tree(tmp, name, files):
    for rel, text in files.items():
        p = os.path.join(tmp, name, "scripts", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
    return os.path.join(tmp, name)


def prev_sim():
    """The frozen 0.22.4 simulator, for the failing-before proofs of the 0.22.5 tests (None when not on this disk)."""
    f = os.path.join(SPECS, "cc0224-build", "scripts", "release_sim.py")
    if not os.path.exists(f):
        return None
    spec = importlib.util.spec_from_file_location("release_sim_0224", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def classes(qs, *cls):
    return [q for q in qs if q["cls"] in cls]


class Blind(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_r1_real_0222_vs_0221_doorbell(self):
        old, new = (os.path.join(SPECS, f"cc022{n}-release", "scripts", "doorbell.py") for n in (1, 2))
        if not (os.path.exists(old) and os.path.exists(new)):
            self.skipTest("0.22.1/0.22.2 release trees not on this disk")
        a = tree(self.tmp, "a", {"doorbell.py": open(old).read()})
        b = tree(self.tmp, "b", {"doorbell.py": open(new).read()})
        qs = RS.questions(a, b)
        self.assertTrue(classes(qs, "doline"), "no Do-line question on the 0.22.2 doorbell change")
        self.assertTrue(classes(qs, "event"), "no event question on the 0.22.2 doorbell change")
        # failing-before proof: the 0.22.3 simulator raises neither class on the same input
        prev = os.path.join(SPECS, "cc0223b-build", "scripts", "release_sim.py")
        if os.path.exists(prev):
            spec = importlib.util.spec_from_file_location("release_sim_0223", prev)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            self.assertEqual(classes(m.questions(a, b), "doline", "event"), [])

    def test_r2_continuation_line_of_do_string(self):
        src = ('def line():\n    return ("Do: first\\n"\n            "{}")\n\n'
               'def other():\n    return 1\n')
        a = tree(self.tmp, "a", {"d.py": src.format("second v1")})
        b = tree(self.tmp, "b", {"d.py": src.format("second v2")})
        qs = classes(RS.questions(a, b), "doline")
        self.assertEqual(len(qs), 1)
        self.assertIn("::line", qs[0]["key"])
        # an unrelated function change raises nothing
        c = tree(self.tmp, "c", {"d.py": src.format("second v1").replace("return 1", "return 2")})
        self.assertEqual(classes(RS.questions(a, c), "doline"), [])

    def test_r3_new_field_on_existing_event(self):
        src = ('def f(store):\n    store.append("x.y", {{"a": 1{}}})\n\ndef g():\n    z = 1{}\n')
        a = tree(self.tmp, "a", {"e.py": src.format("", "")})
        b = tree(self.tmp, "b", {"e.py": src.format(', "b": 2', "")})
        self.assertEqual(len(classes(RS.questions(a, b), "event")), 1)
        multi = 'def f(self):\n    self.store.append(\n        "x.y",\n        {{"a": 1{}}})\n'
        c = tree(self.tmp, "c", {"e.py": multi.format("")})
        d = tree(self.tmp, "d", {"e.py": multi.format(', "b": 2')})
        self.assertEqual(len(classes(RS.questions(c, d), "event")), 1)
        # unrelated changed line in the same file raises none
        e = tree(self.tmp, "e", {"e.py": src.format("", "").replace("z = 1", "z = 2")})
        self.assertEqual(classes(RS.questions(a, e), "event"), [])

    def test_r6_module_constant_read_by_a_do_function(self):       # critic blocker 1 (0.22.4b)
        src = ('TRIG = "{}"\nOTHER = "{}"\n\ndef line():\n    return "Do: " + TRIG\n')
        a = tree(self.tmp, "a", {"d.py": src.format("Do not skip this.", "x")})
        b = tree(self.tmp, "b", {"d.py": src.format("Skip this.", "x")})
        qs = classes(RS.questions(a, b), "doline")
        self.assertEqual(len(qs), 1)
        if prev_sim():     # failing before: the 0.22.4 simulator raises nothing for a changed constant
            self.assertEqual(classes(prev_sim().questions(a, b), "doline"), [])
        # a constant no Do-function reads raises none
        c = tree(self.tmp, "c", {"d.py": src.format("Do not skip this.", "y")})
        self.assertEqual(classes(RS.questions(a, c), "doline"), [])

    def test_r7_payload_built_before_the_append(self):             # critic blocker 2 (0.22.4b)
        src = ('def rec(store):\n    data = {{"a": 1{}}}\n    store.append("x.y", data)\n\ndef other():\n    q = 1{}\n')
        a = tree(self.tmp, "a", {"e.py": src.format("", "")})
        b = tree(self.tmp, "b", {"e.py": src.format(', "b": 2', "")})
        self.assertEqual(len(classes(RS.questions(a, b), "event")), 1)
        if prev_sim():     # failing before: the 0.22.4 simulator misses a payload built on its own line
            self.assertEqual(classes(prev_sim().questions(a, b), "event"), [])
        c = tree(self.tmp, "c", {"e.py": src.format("", "").replace("q = 1", "q = 2")})
        self.assertEqual(classes(RS.questions(a, c), "event"), [])

    def test_r4_no_storm_0223_vs_0222(self):
        a, b = (os.path.join(SPECS, n) for n in ("cc0222-release", "cc0223b-build"))
        if not (os.path.isdir(a) and os.path.isdir(b)):
            self.skipTest("trees not on this disk")
        qs = RS.questions(a, b)
        print(f"R4 questions 0.22.3 vs 0.22.2: {len(qs)}", file=sys.stderr)
        self.assertLessEqual(len(qs), R4_BOUND)


    def test_r8_two_changed_lines_in_one_function_raise_one_question(self):    # 0.22.5 spec R3: grouped per function
        src = ('def rec(store):\n    data = {{"a": 1{}}}\n    n = 1{}\n    store.append("x.y", data)\n')
        a = tree(self.tmp, "a", {"e.py": src.format("", "")})
        b = tree(self.tmp, "b", {"e.py": src.format(', "b": 2', "0")})
        self.assertEqual(len(classes(RS.questions(a, b), "event")), 1)
        two = tree(self.tmp, "two", {"e.py": src.format(', "b": 2', "0") + "\ndef other(store):\n    store.append(\"z\", {\"k\": 1})\n"})
        two0 = tree(self.tmp, "two0", {"e.py": src.format("", "") + "\ndef other(store):\n    store.append(\"z\", {\"k\": 2})\n"})
        self.assertEqual(len(classes(RS.questions(two0, two), "event")), 2)     # a second function is a second question


if __name__ == "__main__":
    unittest.main()
