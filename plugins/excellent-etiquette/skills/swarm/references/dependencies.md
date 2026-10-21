# swarm dependencies

| dependency | why | fallback |
|---|---|---|
| Agent/subagent tool | only some sessions expose it | lead runs parts sequentially, or mails role peers |
| workers have no Harness registration | lead owns identity, leases, commits | none needed |
| device bridge for Exchange/Harness_Router files | workers read/write via device_bash | stage/commit files |
| peer roles need a live holder | mail to a dead role is never read | check roster; else mail queues for next holder and a subagent covers meanwhile |
| file conflicts | parallel writes collide | one exclusive output path per worker; lead merges |
| token budget | cost grows per worker | caps in SKILL.md; outputs go to files, not chat |
| model fallback Haiku->Sonnet (D-f5c9d) | Haiku fails multi-file work | retry once on Sonnet, then lead |
| rate limits | burst dispatch throttles | batch <=5 parallel |
| recursion | runaway cost | forbidden; single-level fan-out only |
| lint 600-token cap | skill body limit | details live in references |
