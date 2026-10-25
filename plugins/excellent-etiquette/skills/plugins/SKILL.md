---
name: plugins
description: "Use when: building, curating or publishing plugins and skills (skill-curation scope)."
---

# plugins

- [role:corpus-envoy] P-24 Alert role:skill-curation-lead immediately on any plugin or skill bug, without asking the operator.
- [global] P-25 The curator (role:skill-curation-lead) owns all custom plugins and skills.
- [global] P-33 Attach every .plugin you build, rebuild or publish in the operator's chat (SendUserFile, display=attach) in the same turn; build not done until attached.
- [global] P-34 Token economy is paramount: minimize always-loaded text, prefer pointers, offload decisions to the corpus.
- Publish gate: see autonomy P-22 (P-20 superseded by P-21).
- [role:curator] P-106 Each release: fold new lessons into skill text; check every scope item against the operator's own words before accepting (L-006); moving a rule out of a skill body keeps a one-line trigger summary (L-007); test with realistic data and compare live-ledger counts before and after (L-005, L-008).
- [global] P-107 Final ACCEPT of a release uses a second reviewer from another model family where available; canary the package to one role for a day first when practical (R-044).
- [global] P-108 Release cadence (D-fffe6): the backlog accumulates in the register; the operator chooses one release per plugin per cycle; nobody cuts a release between cycles, a hotfix needs his approval; the publish check confirms the release matches the cycle (R-057).
