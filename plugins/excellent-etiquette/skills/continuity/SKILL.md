---
name: continuity
description: "Use when: handoffs, new chats, compaction, corpus memory, steward/envoy roles, .DS_Store."
---

# continuity

- [global] P-43 Handoffs easy and recurring: /handoff writes handoffs/<date>-<sobriquet>.md, replies with a one-line bootstrap; new chat at milestones.
- [global] P-44 Before compacting or ending a generation, offload decisions to the corpus (harness_record, pin if durable).
- [global] P-45 A fresh chat with no handoff starts with harness_register project=<project> (no successor_of), then /update.
- [global] P-46 Context thresholds: plan at 130k, handoff at 160k; the 80k/110k proposal is shelved (P-47, P-48 superseded).
- [role:corpus-envoy] P-49 No-carry: no capsules; start from state note, inbox, pinned decisions, runbook; durable direction only via harness_record (D-2fdbb wins).
- [role:corpus-steward] P-41 Ephemeral Haiku worker (D-70499); pin standing rules; never pin live handoff capsules.
- [role:corpus-steward] P-50 Never retain context: fresh register only, never successor_of; archive entries and outputs on retirement.
- [global] P-51 Never bundle, hash, index, stage, commit, read or version .DS_Store; ignore everywhere.
- [global] P-52 OPERATOR.md carries only agent-network directives; do not duplicate Claude account memory preferences.
- [project:cv-management] P-53 On "remember this": save to project memory the same turn, then add to the rules file.
- [role:corpus-steward] P-54 Archive, never delete; claim leases before shared edits; reply via harness_send, not new files; derive indexes from ledger.
- [global] P-101 Local project folders are lowercase-with-dashes (D-8dae9); after the 2026-10-14 cutover project files live under ~/Claude/Code/harness-ops/projects/<project>/ (alias map: harness-ops/_alias/alias-map.json).
- [global] P-104 'Flag it' (operator vocabulary): record the defect or improvement in the corpus and the register, tag it for the next build, notify the owner roles (curator: plugins and skills; secretary: operator queue); do not only change your own behavior (D-19ea6).
- [global] P-105 Lessons, unconditional: on finding an error in yourself or how you acted, add what happened, cause and rule to projects/harness-ops/docs/lessons.md, record it with tag lesson, send it to role:curator (D-19ea6).
