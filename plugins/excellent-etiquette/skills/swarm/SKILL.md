---
name: swarm
description: 'Use when: /swarm [task]; a task has 3+ independent parts to fan out to ephemeral subagents or role peers.'
---

# swarm

`/swarm <task>`. Invocation = approval; do not ask again.
1. Lead writes a spec table: part | owner (ephemeral subagent or role:<x> peer) | model (Haiku mechanical single-file, Sonnet multi-file, lead reviews) | output path | done-check. Show it in one message with a token estimate (P-03), then proceed at once. Ask once only if estimate >200k tokens.
2. Dispatch independent parts in parallel in one turn. Workers retain no context, write only to their assigned path, never spawn others (single-level fan-out). Lead is the only Harness identity and takes harness_claim leases per shared path.
3. Lead verifies every output before use. Failed worker retries once on the next model tier, then lead does it.
4. Merge, harness_record the decision, report <=10 lines.
- No polling: rely on completion notices.
- Max 8 workers, <=5 parallel.
- Dependencies and fallbacks: references/dependencies.md.
