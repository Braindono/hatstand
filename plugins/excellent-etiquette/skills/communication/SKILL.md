---
name: communication
description: "Use when: writing replies, asking questions or options, or addressing roles."
---

# communication

- [global] P-01 Be compressed and structured: summaries and tables, not raw transcripts or tool output; translate machine output into tables with your own suggestions.
- [global] P-02 Always give your recommendation; do not just present data.
- [global] P-03 State token cost of each decision and cost difference between options; plans show token estimates.
- [global] P-04 Never show harness ids (D-/N-/K-/m-) alone; lead with a plain-words description, id optional in parentheses.
- [global] P-05 Address mail to the role (to=role:<name>), never an agent id or sobriquet; roster via harness_admin op=roster.
- [global] P-06 Present questions and suggestions as selectable options via AskUserQuestion, not plain-text lists.
- [global] P-07 Number questions n/N (1/2, 2/2); this is the default (P-11 applies only inside cv-management edits).
- [global] P-08 Put the recommended option first, labelled "(Recommended)".
- [global] P-09 Tag every answer or option with confidence: green High, yellow Medium, white Low.
- [global] P-96 Every open question you raise carries your own suggestion and a default; a pending list is worked without asking permission (extends P-92).
- [global] P-97 A table needing more than one operator action is a questionnaire (categorical answers, info-only rows for context), never a prose table. Show a daily checklist of completed items. Cross-agent operator items go in Exchange/action-items/<role>.md (README format, max 4 rows per table).
- [global] P-98 A local file or folder pointed to in chat is a markdown link with a computer:// URL, e.g. [job-digest](computer:///Users/btf/Claude/Projects/Exchange/projects/cv-management/job-digest); never a bare path. Where links cannot render, give the full absolute path in a code block.
- [global] P-99 A command for the operator goes in ONE fenced code block, full command on one line (python3 <absolute path> ...), no placeholders; join several with &&.
- [global] P-100 While waiting on another agent's reply, show one status line in chat: who, about what, next step (D-3a5b3).
