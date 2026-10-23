# autonomy: more global rules (moved verbatim from SKILL.md in 0.2.8 to keep the body <=600 tokens)

- [global] P-91 "Remind me", "don't let me forget", "follow up on": same turn harness_send to=role:secretary kind=notice subject=REMINDER body=`REMIND|<ISO date or none>|<text>|<source>`; confirm briefly.
- [global] P-94 After mail needing a reply, check harness_inbox (wait<=45) at ~30s, 2m, 10m, then stop; skip if ctx >150k or handoff triggered.
