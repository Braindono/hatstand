# Coordination patterns

Every pattern uses the same primitives: `send` (with `kind`, `reply_to`, `refs`), `inbox`, `task_update`, `claim`, `commit` and `release`. The thread tree is what records the shape: `parent` links plus `hop` counts.

## Sequence (pipeline)

A → B → C, each stage consuming the previous one's output.

1. A: `send(to=B, kind=handoff, subject="Stage 2: …", body=state+next steps, refs=[outputs])`.
2. B: `task_update(working)` → does the work → `send(to=C, kind=handoff, reply_to=<A's msg>)` → `task_update(<A's msg>, completed)`.
3. C replies with `kind=result` to B's message. Use `to="B,A"` if A must know.

Keep `reply_to` chained so the entire pipeline stays in one thread.

## Branch (fan-out and fan-in)

One coordinator, N parallel workers, one merge.

1. Coordinator: `group` join is optional. `send(to="group:reviewers" or "B,C,D", kind=task, expects_reply=true)`. One message produces N deliveries and one thread.
2. Each worker replies with `reply_to=<task msg>` and `kind=result`. The replies become sibling branches in the tree.
3. Coordinator: `inbox(wait=30)` until all N results arrive (compare `from` against the list sent to), then merge.
4. **Fan-out over a shared file:** each worker claims a *different* file or section file. If they must touch the same file, run them in sequence through the lease.

## Loop (iterate until done)

Author ↔ reviewer until accepted, or until a budget runs out.

1. Author: `send(to=R, kind=review request as task, max_hops=10)`, which sets the thread's loop budget.
2. Reviewer: `reply_to` with `kind=review`. The body includes the verdict: `ACCEPT` or `REVISE: <specific points>`.
3. Author: on `REVISE`, claim, edit, commit, release, then `reply_to` with `kind=result`. On `ACCEPT`, `task_update(completed)`.
4. If the loop guard refuses a send, the budget is exhausted. Send a summary to `human` with `kind=question` asking for a decision.

Every iteration should shrink the list of open points. If two rounds pass with no progress, escalate early.

## Combinations

- **Pipeline with a review loop per stage:** each stage is a loop thread, and the handoff to the next stage is a `reply_to` on the accepted result.
- **Fan-out, then merge, then loop:** workers return results, the coordinator merges them into a shared file under a lease, then opens a review loop on the merged artifact.
- **Supervisor:** one agent watches `inbox(wait=60)` and routes by expertise. It reads the ledger (`harness_admin` op=ledger) to pick the agent whose confirmed expertise fits, then sends `kind=task`. This is the precursor of the planned local orchestrator.

## Handoff body template

```
STATE: what is done (with commit versions)
REFS: files touched and their versions
NEXT: concrete next steps, in order
OPEN: unresolved questions or risks
DONE WHEN: acceptance criteria
```

## Etiquette

- One topic per thread. Keep subjects short and specific.
- Never send broadcasts (`*`) for task work. Use explicit targets or groups.
- Do not poll in tight loops. Use `inbox(wait=…)`.
- Before handing off, release your leases, or tell the receiver in the body that you are keeping one and why.

## Ladder (moved from SKILL.md)
After a `task`/`question`/`review` send, follow the result's `ladder`: `harness_inbox wait=<n>` per entry (15, then 2×30, then 3×40; no call over `wait=45`; `inbox-ladder:` in OPERATOR-PREFERENCES.md, `off` disables). First mail ends it; all empty → "still waiting on <id>", end turn. `notice`/`result` start no ladder and need no reply. `[scheduled]` runs and Haiku never listen. D-ec4c9 role wake if the answer is minutes away.

## Corpus
`title` one line, `body` terse why, `tags` 1–3 lowercase. Changed decision → new entry `supersedes=<id>`; never edit old ones. Cite by id. Recall cards first; `ids=[…]` only if needed.

- After an offload capsule keep only its id.

## Inbox
A Stop hook adds one reminder line if a reply had no inbox call.

## Threads (moved from SKILL.md)
`reply_to` continues a thread. Loop guard refusal → `operator` `question`. Task states: `harness_admin op=task_update`.

