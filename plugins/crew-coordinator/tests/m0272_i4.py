"""0.27.2 matrix rows for I4 (scope_warnings reads the gate-file phrase with the gate's own regex and the simulator's own file set). Each ROWS entry is one row of the I4 table:
fn(testcase). Depends on: scripts/harness.py (scope_warnings, SCOPE_GATE_RE, _release_gate), scripts/release_sim.py (GATE_FILES, GATE_FUNCS)."""
import inspect, os, shutil, sys, tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H
import release_sim as RS

HARNESS = "scripts/harness.py"
RG = "scripts/release_guard.py"
LONG = "x" * 201


def tree(tc, files=(), funcs=()):
    """-> (previous, candidate): every gate file present in both; the named files and the named functions of scripts/harness.py differ in the candidate."""
    d = tempfile.mkdtemp(prefix="i4-")
    tc.addCleanup(shutil.rmtree, d, True)
    out = []
    for side in ("prev", "cand"):
        root = os.path.join(d, side)
        for rel in RS.GATE_FILES:
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w") as f:
                f.write("changed\n" if side == "cand" and rel in files else "same\n")
        os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
        with open(os.path.join(root, HARNESS), "w") as f:
            f.write('APPROVAL_ACTIONS = ("a", "b")\n\n')
            for fn in ("publish_release", "_release_gate"):
                f.write("def %s():\n    return %d\n\n" % (fn, 2 if side == "cand" and fn in funcs else 1))
        out.append(root)
    return out[0], out[1]


def warn(items, trees=None, rationale=""):
    prev, cand = trees or (None, None)
    return H.Harness.scope_warnings({"items": items, "rationale": rationale}, candidate_tree=cand, previous_tree=prev)


def phrase(path):
    return "Gate file changed: " + path


def r_exact_phrase(tc):
    tc.assertEqual(warn([phrase(RG)], tree(tc, files=[RG])), [])
    tc.assertEqual(warn([phrase(RG)]), [])
    tc.assertEqual(warn([phrase("scripts/retire_guard.py")], tree(tc, files=["scripts/retire_guard.py"])), [])      # a file only the simulator's six-file set knows


def r_trailing_period(tc):
    w = warn([phrase(RG + ".")], tree(tc, files=[RG]))
    tc.assertTrue(any("'scripts/release_guard.py.'" in x and "matches no gate file" in x for x in w), w)


def r_text_after(tc):
    for text in (phrase(RG + ". Tests added"), phrase(RG) + " (hooks too)"):
        w = warn([text], tree(tc, files=[RG]))
        tc.assertTrue(any("scripts/release_guard.py" in x and ("Tests added" in x or "hooks too" in x) for x in w), (text, w))


def r_list_with_and(tc):
    w = warn(["Gate files changed: scripts/release_guard.py, scripts/retire_guard.py and hooks/hooks.json"], tree(tc, files=[RG]))
    tc.assertTrue(any("'scripts/retire_guard.py and hooks/hooks.json'" in x for x in w), w)
    tc.assertFalse(any("'scripts/release_guard.py'" in x and "matches no" in x for x in w), w)


def r_case(tc):
    for text in ("GATE FILE CHANGED: " + RG, "gate file changed: " + RG, "Gate Files Changed: " + RG):
        tc.assertEqual(warn([text], tree(tc, files=[RG])), [], text)
    tc.assertTrue(warn([phrase(RG.upper())]))                                        # the path itself is compared exactly


def r_func_pair(tc):
    for fn in ("publish_release", "_release_gate"):
        tc.assertEqual(warn([phrase(f"{HARNESS}::{fn}")], tree(tc, funcs=[fn])), [], fn)
    tc.assertEqual(warn([phrase(f"{HARNESS}::publish_release")]), [])


def r_func_not_a_pair(tc):
    w = warn([phrase(f"{HARNESS}::sync")], tree(tc, funcs=["publish_release"]))
    tc.assertTrue(any("scripts/harness.py::sync" in x and "matches no gate" in x for x in w), w)


def r_hooks_json_no_phrase(tc):
    w = warn(["ordinary item about hooks"], tree(tc, files=["hooks/hooks.json"]))
    tc.assertEqual(len([x for x in w if "hooks/hooks.json" in x]), 1, w)
    tc.assertIn("Gate file changed: hooks/hooks.json", " ".join(w))


def r_named_but_unchanged(tc):
    w = warn([phrase(RG)], tree(tc, files=["scripts/release_sim.py"]))
    tc.assertTrue(any(RG in x and "did not change" in x for x in w), w)


def r_changed_not_captured(tc):
    w = warn(["something else"], tree(tc, files=[RG], funcs=["_release_gate"]))
    tc.assertTrue(any(RG in x and "Gate file changed: " + RG in x for x in w), w)
    tc.assertTrue(any(f"{HARNESS}::_release_gate" in x and f"Gate file changed: {HARNESS}::_release_gate" in x for x in w), w)


def r_nothing_changed(tc):
    tc.assertEqual(warn(["plain item"], tree(tc)), [])


def r_no_trees_existing_check(tc):
    w = warn(["release_guard.py was reworked"])
    tc.assertEqual(len(w), 1, w)
    tc.assertIn("described as changed", w[0])


def r_long_items_and_cap(tc):
    w = warn([LONG] * 10)
    tc.assertEqual(len(w), 6)
    tc.assertTrue(all("characters" in x for x in w))


def r_not_importable(tc):
    with mock.patch.dict(sys.modules, {"release_sim": None}):
        w = warn(["release_guard.py was reworked"], tree(tc, files=[RG]))
    tc.assertEqual(sum("cannot be imported" in x for x in w), 1, w)
    tc.assertTrue(any("described as changed" in x for x in w), w)                    # the older check still ran


def r_path_forms(tc):
    w = warn([phrase("./" + RG)], tree(tc, files=[RG]))
    tc.assertTrue(any("'./scripts/release_guard.py'" in x for x in w), w)
    w = warn(["Gate file changed: scripts\\release_guard.py"], tree(tc, files=[RG]))
    tc.assertTrue(any("'scripts'" in x for x in w), w)                                # the regex stops at the backslash: the captured string is shown


def r_same_regex_and_split(tc):
    src = inspect.getsource(H.Harness._release_gate)
    tc.assertIn("self.SCOPE_GATE_RE.finditer", src)
    tc.assertIn('m.group(1).split(",")', src)
    tc.assertIn("x.strip()", src)
    items = ["Gate files changed: a.py, b.py and c.py", "gate file changed: x.py. more", "none", "Gate file changed:  p.py ,q.py"]
    gate_way = {x.strip() for it in items for m in H.Harness.SCOPE_GATE_RE.finditer(str(it)) for x in m.group(1).split(",") if x.strip()}
    tc.assertEqual({e for e, _ in H.Harness.scope_gate_phrases(items)}, gate_way)


def r_gate_set_is_the_simulators(tc):
    src = inspect.getsource(H.Harness._gate_phrase_warnings)
    tc.assertIn("RS.GATE_FILES", src)
    tc.assertIn("RS.GATE_FUNCS", src)
    tc.assertEqual(len(RS.GATE_FILES), 6)


ROWS = {"I4-01": r_exact_phrase, "I4-02": r_trailing_period, "I4-03": r_text_after, "I4-04": r_list_with_and, "I4-05": r_case, "I4-06": r_func_pair,
        "I4-07": r_func_not_a_pair, "I4-08": r_hooks_json_no_phrase, "I4-09": r_named_but_unchanged, "I4-10": r_changed_not_captured, "I4-11": r_nothing_changed,
        "I4-12": r_no_trees_existing_check, "I4-13": r_long_items_and_cap, "I4-14": r_not_importable, "I4-15": r_path_forms, "I4-16": r_same_regex_and_split,
        "I4-17": r_gate_set_is_the_simulators}
