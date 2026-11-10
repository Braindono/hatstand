---
name: continuity
description: "Use when: handoffs, new chats, compaction, corpus memory, steward/envoy roles, .DS_Store."
---

# continuity

- [global] P-43 Handoffs easy and recurring: /handoff writes handoffs/<date>-<sobriquet>.md, replies with a one-line bootstrap; new chat at milestones.
- [global] P-44 Before compacting or ending a generation, offload decisions to the corpus (harness_record, pin if durable).
- [global] P-45 A fresh chat without handoff starts with harness_register project=<project> (no successor_of), then /update.
- [global] P-46 Context thresholds: plan 130k, handoff 160k; the 80k/110k proposal is shelved (P-47/P-48 superseded).
- [role:corpus-envoy] P-49 No-carry: no capsules; start from state note, inbox, pinned decisions, runbook; durable direction only via harness_record (D-2fdbb wins).
- [role:corpus-steward] P-41 Ephemeral Haiku worker (D-70499); pin standing rules; never pin live handoff capsules.
- [role:corpus-steward] P-50 Never retain context: fresh register only, never successor_of; archive entries and outputs at retirement.
- [global] P-51 Never bundle, hash, index, stage, commit, read or version .DS_Store; ignore everywhere.
- [global] P-52 OPERATOR.md carries only agent-network directives, no copies of Claude account memory preferences.
- [project:cv-management] P-53 On "remember this": save to project memory the same turn, then to the rules file.
- [role:corpus-steward] P-54 Archive, never delete; claim leases before shared edits; reply via harness_send, not new files; derive indexes from ledger.
- [global] P-101 Project folders are lowercase-with-dashes (D-8dae9); full text and alias map: references/more.md.
- [global] P-104 'Flag it' (operator word): record the defect or improvement in corpus and register, tag it for the next build, notify the owners (curator: plugins, skills; secretary: operator queue); not only change your own behavior (D-19ea6).
- [global] P-105 Lessons, always: on an error in yourself or how you acted, add what happened, cause and rule to projects/harness-ops/docs/lessons.md, record it with tag lesson, send it to role:curator (D-19ea6).
- [global] P-110 Multi-agent documents: ONE Claude Doc; read your Members access first; [Rationale]/[Rebuttal] comments; only the operator resolves. references/shared-docs.md.
- [global] P-111 Ideas: record one you propose or the operator tells you the same turn (kind=note tags=[idea]); relay an operator idea once to role:secretary; recall first, skip if already noted; work never waits.
