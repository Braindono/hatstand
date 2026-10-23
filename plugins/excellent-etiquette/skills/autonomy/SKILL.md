---
name: autonomy
description: "Use when: deciding whether to act or ask: approvals, mail replies, role handoffs, publish gates."
---

# autonomy

- [global] P-16 Coordinate with other roles without approval; escalate only governance, publication, blockers.
- [global] P-17 Reply to agent mail automatically, no operator prompt (D-c9982); close retired threads.
- [global] P-19 Taking over a role from a handoff needs no approval; ask once only if the outbound model was higher.
- [global] P-21 With all prerequisites collected, proceed without asking or prompting; an unqualified task is implied approval.
- [global] P-22 No publish without an envoy ACCEPT on the build thread naming the linted package sha.
- [global] P-80 Interrupt the operator only for: publish approval; irreversible action; credentials, security or spend; contradictory instructions; nobody can decide. Else decide, harness_record, continue. Release scope (items, version numbers, splitting, deferring, bundling) is the operator's decision: propose it with context and rationale, then wait. "Decide, record, continue" does not cover scope.
- [global] P-81 Agent proceed/ack/FYI traffic and "may I proceed?" never reach the operator: sender states its default and proceeds; receiver decides, answers once, one line, forwards only per P-80; never ack an ack. Builders and the curator never cut, split or renumber a release on their own.
- [global] P-82 Batch non-critical questions in one <=5-line digest, each with a default and review_by; reversible items take the default at lapse; irreversible, publish, spend, credential items never.
- [global] P-84 Suggest /swarm once for >=3 independent parts.
- [global] P-85 Offer a better path via AskUserQuestion, recommended first; propose an alliterative name before building any plugin or skill.
- [global] P-87 Mail needing an answer says "reply immediately via harness_send"; on init/restore with mail waiting, reply first.
- [global] P-88 Act on corpus-check and lint WARNs: fix what you own, send kind=review to the owner role (D-1e728).
- [global] P-92 On restore/resume: own pending-actions list first, then harness_inbox, then work unprompted. Stop only for P-80.
- [global] P-93 "Remember this": also notice role:skill-curation-lead (index = owner map).
- [global] P-91 remind-me: REMIND to role:secretary. P-94 inbox re-check after mail needing a reply. See references/more.md.
- Scoped rules (cv-management, letters-manager, corpus-envoy, secretary): references/scoped.md (P-18, P-23, P-26..P-31, P-95).
