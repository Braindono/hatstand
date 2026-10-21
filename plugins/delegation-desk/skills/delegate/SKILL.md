---
name: delegate
description: Use when a mechanical step (crawl, parse, lint, diff, export) can go to a cheap ephemeral subagent.
---

# Delegate

## Delegate when
- The step is mechanical and checkable: crawl, extract, parse, convert, render or export, lint, diff, summarize a file set.
- The inputs can be named in a few lines (paths, ids, a spec). The worker needs no conversation history.

## Never delegate
- Governance: approving content, template or design changes, ownership decisions, anything addressed to your role for a ruling.
- Style or voice work you are being trained on. Keep it in your own context.
- Harness identity actions: register, role, lease, ticket moves, and messages sent as you.

## How
1. Use the Agent tool with `model: "haiku"` (general-purpose) unless the step needs judgment. Then use a mid-tier model and say why.
2. Prompt = goal + exact input paths + output path/format + a stop condition + "return ≤10 lines: result, output paths, anomalies". No chat history, no persona.
3. Parallelize only independent steps. Keep it to ≤3 workers unless the operator asked for scale.
4. Verify before acting: open the output, spot-check one item, then commit or send. A worker's claim is not evidence.
5. Workers never call harness tools. You claim leases, commit versions and move tickets.
6. Record only the outcome (ids, paths) in your context. Discard the worker transcript.
7. Step cap: an agent may specify a tool-call cap N; at N−3 calls, stop and deliver what you have (don't wait for the cap or try to optimize further).
8. Return contract: report ≤400 words; quoted tool output max head 5000 + tail 5000 chars, with a 'narrow your command' hint when cut.
