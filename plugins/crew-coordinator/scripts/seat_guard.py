"""seat_guard: keeps the operator seat human-only and keeps broadcasts out of it.

What it does: refuses any attempt by an agent chat to hold the operator seat (role, task or succession),
and filters the operator seat's holders out of "*" broadcasts.
Why: an agent that holds the seat can mail as him and be believed. Broadcast mail is not meant for him.
Depends on: nothing outside the standard library; callers pass the ledger state object (State) in.
Interface: SEAT, is_seat(role), refuse_if_seat(role, task, pred_role, holder_ok=False), seat_agent_ids(st), exclude_seat(ids, st).
"""
SEAT = "operator"

REFUSAL = ("the operator seat is his alone: no agent chat may restore, register or succeed it. "
           "He registers at his own Terminal; see the operator-seat install text.")


def is_seat(role):
    """True when `role` names the operator seat (case and spacing ignored)."""
    return str(role or "").strip().lower() == SEAT


def refuse_if_seat(role=None, task=None, pred_role=None, holder_ok=False):
    """Raise ValueError(REFUSAL) when role, a task named after the seat, or the predecessor's role is the seat.
    holder_ok is set only by a caller that already passed the signed operator gate."""
    if holder_ok:
        return
    for v in (role, task, pred_role):
        if is_seat(v):
            raise ValueError(REFUSAL)


def seat_agent_ids(st):
    """Ids of every agent whose current role is the operator seat."""
    out = set()
    for aid in list(st.agents):
        try:
            if is_seat(st.role_of(aid)):
                out.add(aid)
        except Exception:
            continue
    return out


def exclude_seat(ids, st):
    """Drop seat holders from a list of agent ids (used for "*" fan-out)."""
    seat = seat_agent_ids(st)
    return [i for i in ids if i not in seat]
