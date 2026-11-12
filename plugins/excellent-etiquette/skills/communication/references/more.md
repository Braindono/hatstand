# communication: detail moved verbatim from SKILL.md in 0.2.9 (triggers stay in the body)

- [global] P-97 A table needing more than one operator action is a questionnaire (categorical answers, info-only rows for context), never a prose table. Show a daily checklist of completed items. Cross-agent operator items go in Exchange/action-items/<role>.md (README format, max 4 rows per table).
- [global] P-98 A local file or folder pointed to in chat is a markdown link with a computer:// URL, e.g. [job-digest](computer:///absolute/path/to/job-digest); never a bare path. Where links cannot render, give the full absolute path in a code block.

## P-04 example (bare codes, added in 0.2.13)
Not: "answer R3". Instead: "Should the weekly report include costs? Answer in the Hub, Questionnaire tab (link): tap Yes or No (R3)." Codes like R1-R14, W45 or hk3 appear only in parentheses after the words.

## Operator steps (P-99 detail)
- His steps go to role:secretary's Hub queue, dry run first, not asked in a role's chat; if he asks for a command in a chat, answer there and still log it to the queue; when role:secretary is vacant or handed off, the step waits in the queue and the role tells the envoy. Command format: one fenced block, full command on one line (python3 <absolute path> ...), no placeholders. Dry run first and alone; the next command only after its result; one approve command per id, never a loop. The old advice to paste a command in chat with a leading ! is dropped: the desktop app has no ! commands.

## P-102 full text
- [global] P-102 Be skeptical of your own plans: say what is unverified, treat estimates as floors, check results on disk, measure yourself with the gauge (D-1aeb7).
