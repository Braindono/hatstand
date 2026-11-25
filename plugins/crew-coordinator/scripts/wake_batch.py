"""0.27.3 B (F6): batch the wake steps of one send. Pure helpers, stdlib only; no ledger access, no events.
Used by doorbell._do_many (steps) and doorbell._relay_target (relay order). Depends on: nothing.
* `group_by_shape(items)`: recipients [(hid, trigger)] -> one group per route shape (by id only, by trigger only, both), in first-seen order,
  each group {"hids": [...], "trigs": [...]} with duplicates merged. One group = one step set, however many children it holds.
* `paired_trigs(items)`: the trigger text of a group whose children have BOTH a session id and a trigger: each trigger named with its child
  ("t1 for A and t2 for B"), so one delivered and one refused child is unambiguous. One child (or none with both): the bare trigger, as before.
* `smallest_first(cands, ctx_of)`: candidates ordered by recorded context size ascending; a candidate with no recorded size sorts last;
  ties and missing sizes keep the given order (stable)."""


def group_by_shape(items):
    groups = {}
    for hid, trig in items:
        g = groups.setdefault((bool(hid), bool(trig)), {"hids": [], "trigs": []})
        if hid and hid not in g["hids"]:
            g["hids"].append(hid)
        if trig and trig not in g["trigs"]:
            g["trigs"].append(trig)
    return list(groups.values())


def paired_trigs(items):
    """items: [(hid, trig)]. -> 'T1 for A and T2 for B' over the children that have both; None when no child has a trigger."""
    pairs = list(dict.fromkeys((h, t) for h, t in items if h and t))
    if len(pairs) < 2:
        return pairs[0][1] if pairs else None
    return " and ".join(f"{t} for {h}" for h, t in pairs)


def _size(v):
    try:
        return (0, float(v)) if v is not None and not isinstance(v, bool) and float(v) >= 0 else (1, 0.0)
    except (TypeError, ValueError):
        return (1, 0.0)


def smallest_first(cands, ctx_of):
    """cands: any list; ctx_of(c) -> recorded ctx or None. -> new list, smallest known size first (stable)."""
    return sorted(cands, key=lambda c: _size(ctx_of(c)))
