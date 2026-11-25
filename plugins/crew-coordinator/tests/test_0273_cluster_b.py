"""0.27.3 cluster B (F6): child wakes batched into one step set per route shape; relay target = the smallest live chat.
Run: python3 -B -m unittest tests.test_0273_cluster_b"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import doorbell as D
import wake_batch as W


class FakeSt:
    def __init__(self, ctxs, roles=None):
        self.agents = {k: {"ctx": v} for k, v in ctxs.items()}
        self.wake_reg = {}
        self._roles = roles or {k: "r_" + k for k in ctxs}

    def role_of(self, k):
        return self._roles.get(k)

    def role_holder(self, role):
        return None

    def name_role(self, k):
        return k


def relay(ctxs, hids, stale=()):
    st = FakeSt(ctxs)
    offer = {"to": list(ctxs), "hids": hids}
    with mock.patch.object(D, "_stale_ids", return_value=set(stale)), mock.patch.object(D, "_same_machine", return_value=True), \
            mock.patch.object(D, "_wake_trigger", return_value=None):
        return D._relay_target(None, st, offer)


class Batch(unittest.TestCase):
    def test_grouping_merges_children_of_one_shape(self):
        g = W.group_by_shape([("local_a", None), ("local_b", None), ("local_a", None), (None, "T1"), (None, "T2"), ("local_c", "T1")])
        self.assertEqual(g, [{"hids": ["local_a", "local_b"], "trigs": []}, {"hids": [], "trigs": ["T1", "T2"]},
                             {"hids": ["local_c"], "trigs": ["T1"]}])

    def test_mixed_shapes_give_one_send_step_for_all_id_children(self):
        ring = [("a1", "x", "local_a", None), ("a2", "x", "local_b", None), ("a3", "x", "local_c", None), ("a4", "x", None, "TRIG1")]
        out = D._do_many(ring, "LINE", "m-1", FakeSt({}))
        self.assertEqual(out.count("Do: SendMessage to"), 1)
        self.assertIn("local_a and local_b and local_c (one send each, the same text)", out)
        self.assertEqual(out.count("Do: RemoteTrigger"), 1)

    def test_one_report_per_recipient_survives_batching(self):
        ring = [("a1", "x", "local_a", None), ("a2", "x", "local_b", None), ("a3", "x", None, "TRIG1")]
        out = D._do_many(ring, "LINE", "m-1", FakeSt({}))
        self.assertIn("One report per recipient", out)
        for k in ("local_a", "local_b", "a3"[:8]):
            self.assertIn(k, out.split("One report per recipient")[1])
        self.assertIn('to:"<one of the to values>"', out)

    def test_single_and_same_shape_paths_unchanged(self):
        one = D._do_many([("a1", "x", "local_a", None)], "LINE", "m-1", FakeSt({}))
        self.assertEqual(one, D._do_one("local_a", None, "LINE", "m-1", fields=False))
        two = D._do_many([("a1", "x", "local_a", None), ("a2", "x", "local_b", None)], "LINE", "m-1", FakeSt({}))
        self.assertEqual(two.count("Do: SendMessage to"), 1)

    def test_different_shapes_without_batching_would_have_been_more_steps(self):
        ring = [("a1", "x", "local_a", None), ("a2", "x", "local_b", None), ("a3", "x", "local_c", "TRIG1"), ("a4", "x", "local_d", "TRIG1")]
        out = D._do_many(ring, "LINE", "m-1", FakeSt({}))
        self.assertEqual(out.count("Do: SendMessage to"), 2)       # one for the id-only shape, one for the both shape, not four


class PairedTriggers(unittest.TestCase):      # 0.27.3 F N4
    def test_both_shape_children_name_each_trigger_with_its_child(self):
        ring = [("a1", "x", "local_a", "T1"), ("a2", "x", "local_b", "T2")]
        out = D._do_many(ring, "LINE", "m-1", FakeSt({}))
        self.assertIn("trigger_id=T1 for local_a and T2 for local_b", out)
        self.assertEqual(out.count("Do: RemoteTrigger"), 1)
        rep = out.split("One report per recipient")[1]
        self.assertIn("local_a", rep); self.assertIn("local_b", rep)
        self.assertIn('to:"<one of the to values>"', out)       # one nudge_result per recipient, each with its own to

    def test_mixed_group_pairs_only_the_both_children(self):
        ring = [("a1", "x", "local_a", None), ("a2", "x", "local_b", "T1"), ("a3", "x", "local_c", "T2"), ("a4", "x", None, "T3")]
        out = D._do_many(ring, "LINE", "m-1", FakeSt({}))
        self.assertIn("T1 for local_b and T2 for local_c", out)
        self.assertIn("trigger_id=T3 ", out)
        self.assertNotIn("T3 for", out)

    def test_one_both_child_keeps_the_bare_trigger(self):
        self.assertEqual(W.paired_trigs([("local_a", "T1")]), "T1")
        self.assertIsNone(W.paired_trigs([("local_a", None), (None, "T2")]))
        self.assertIsNone(W.paired_trigs([("local_a", None)]))
        self.assertEqual(W.paired_trigs([("local_a", "T1"), ("local_b", "T1"), ("local_a", "T1")]), "T1 for local_a and T1 for local_b")


class Smallest(unittest.TestCase):
    def test_lowest_ctx_wins(self):
        self.assertEqual(relay({"a": 900, "b": 100, "c": 500}, ["local_a", "local_b", "local_c"]), ("b", "local_b", None))

    def test_missing_ctx_sorts_last_and_no_ctx_keeps_order(self):
        self.assertEqual(relay({"a": None, "b": 400}, ["local_a", "local_b"]), ("b", "local_b", None))
        self.assertEqual(relay({"a": None, "b": None}, ["local_a", "local_b"]), ("a", "local_a", None))

    def test_ties_keep_the_existing_order(self):
        self.assertEqual(relay({"a": 200, "b": 200}, ["local_a", "local_b"]), ("a", "local_a", None))

    def test_stale_or_non_local_candidates_are_never_picked(self):
        self.assertEqual(relay({"a": 900, "b": 100, "c": 500}, ["local_a", "local_b", "cowork_c"], stale=["local_b"]), ("a", "local_a", None))
        self.assertIsNone(relay({"a": 1}, ["local_a"], stale=["local_a"]))

    def test_smallest_first_is_stable_and_total(self):
        self.assertEqual(W.smallest_first(["x", "y", "z"], {"x": None, "y": 5, "z": "bad"}.get), ["y", "x", "z"])


if __name__ == "__main__":
    unittest.main()
