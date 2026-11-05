# Release questions

One question per change against the installed release (0.22.1). Answers by the ops-coder; the harness-critic judges them.

The installed 0.22.1 simulator generated no questions for this tree. It asks about a changed Do-line only when the changed line itself
contains "Do:", and about events only when an event TYPE appears or goes, so it missed both changes below. The two answers are given
by hand, without Q- ids, so they are not counted by the gate. Gate gap reported to the curator.

## Do-line text changed in scripts/doorbell.py::_do_one (not detected)
Which sender acts on it, and what if that sender lacks the tool it names?
Answer: The sender of a task, question, review, handoff or result to a role with a pinned wake trigger. Two text changes, both fixed
strings with no mail text: (1) the trigger step now always carries "Do not skip this step because the mail is not urgent."; (2) with a
chat id, its condition reads "only if the SendMessage step above did not deliver or the session holds it". A sender without RemoteTrigger
still skips with reason no_remotetrigger, without SendMessage with no_sendmessage, unchanged. Notices still get no trigger step. No
ListAgents wording (gate I3b passes).

## Event field added: nudge.result `for` and `evidence` (not detected)
Who reads it, and is docs/EVENTS.md current?
Answer: Written by record_result. `by` is the reporter and `for` is the offer's sender, on every result. `evidence` {http, session,
self_reported: true} appears only when a relaying agent, not the sender, reports with a 3-digit HTTP status and a cse_/session_ id in its
reason. Readers (alarm_scan, outcomes) key on msg_id and ignore the new fields. EVENTS.md row updated; its pin in hatstand_guard.py
updated with it.
