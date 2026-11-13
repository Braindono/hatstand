# Release questions

One question per change against the installed release. Answer every one; the gate fails on a blank answer.

## Q-a9b98aad event: scripts/doorbell.py::record_result#d4de078e
store.append( call, or a function that holds one, changed in scripts/doorbell.py::record_result (8 line(s)): a new field or changed payload on an event type. Who reads it, and is docs/EVENTS.md current?
Answer: No new field and no new event type: the nudge.result `status` (int), written since 0.24.0 only on woke, is now also written on a held or skipped report on a trigger offer when the reason carries an HTTP status; a skipped report with a 2xx status is refused. Reader: the State fold (trig_fires, now a 4-tuple with a gone flag) read only by doorbell.fire_stale; old events without status fold by their reason text. docs/EVENTS.md is NOT updated in this release: its `nudge.result` rows still say status is stored for woke only. It is a pinned file the hotfix lane does not touch; the line goes into the next feature release (0.25.0).
