# communication: detail moved verbatim from SKILL.md in 0.2.9 (triggers stay in the body)

- [global] P-97 A table needing more than one operator action is a questionnaire (categorical answers, info-only rows for context), never a prose table. Show a daily checklist of completed items. Cross-agent operator items go in Exchange/action-items/<role>.md (README format, max 4 rows per table).
- [global] P-98 A local file or folder pointed to in chat is a markdown link with a computer:// URL, e.g. [job-digest](computer:///Users/btf/Claude/Projects/Exchange/projects/cv-management/job-digest); never a bare path. Where links cannot render, give the full absolute path in a code block.

## P-04 example (bare codes, added in 0.2.13)
Not: "answer R3". Instead: "Should the weekly report include costs? Answer in the Hub, Questionnaire tab (link): tap Yes or No (R3)." Codes like R1-R14, W45 or hk3 appear only in parentheses after the words.
