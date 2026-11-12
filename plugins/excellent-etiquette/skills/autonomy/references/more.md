# autonomy: more global rules (moved verbatim from SKILL.md in 0.2.8 and 0.2.10 to keep the body <=600 tokens)

- [global] P-91 "Remind me", "don't let me forget", "follow up on": same turn harness_send to=role:secretary kind=notice subject=REMINDER body=`REMIND|<ISO date or none>|<text>|<source>`; confirm briefly.
- [global] P-94 After mail needing a reply, check harness_inbox (wait<=45) at ~30s, 2m, 10m, then stop; skip if ctx >150k or handoff triggered.
- [global] P-85 Offer a better path via AskUserQuestion, recommended first; propose an alliterative name before building any plugin or skill.
- [global] P-109 Self-report: the moment you notice your own miss (wrong claim, skipped step, broken rule), mail role:secretary unprompted with what happened, the cause and the fix; the secretary files it as a lesson (D-f83f8).
- [global] Each install or settings step for the operator gets a full Hub write-up (what, why, before/after, risk, steps, check, undo); role:secretary alerts him.
- [global] A shell command blocked by the sandbox is not retried outside it; mail role:secretary kind=task with the role, the blocked host or path, the purpose, and whether work stopped.
