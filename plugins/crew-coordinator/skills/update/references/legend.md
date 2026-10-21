# /update legend

First line: `✓ current #seq` (nothing to do) or `△ N do · M changed #seq`, plus `ctx ~Nk ok|plan|now` when you pass `ctx` (plan = hand off soon, now = run /handoff).

## Do lines
| Mark | Do |
|---|---|
| `⛔ STOP` | You were superseded. Stop working as this agent. |
| `✕ restart` | Run `/reload`, then tell the operator. New chat only if a tool or param is still missing. |
| `✕ plugin behind` | Ask the operator to install the current release. |
| `☞ operator` | Apply the operator's notes. Ask if they conflict with your task. |
| `✉n` | Call `harness_inbox`. |
| `★ path` | Someone else changed a file you depend on. Re-read it before editing. |
| `◇n` | roster changed (n events): `harness_admin op=roster since=<your last seq>` if you need who holds which role |
| `⚑ path` | Leased by another agent. Coordinate before editing. |
| `≈ path` | Changed on disk outside the harness. Re-read it. |
| `⏳ path` | Lease expiring. Renew it with `harness_claim` or release it. |
| `⚙` | Claude config or plugins changed. Check for new skills. |

## Health rows (shown only when their state changes)
`● ok  ▲ attention  ✕ broken`

| Cell | Meaning |
|---|---|
| `reg ✓` | Your code matches the release registry |
| `reg ▲x` / `reg ▼x` | Newer unreleased build / behind the published version |
| `reg ≠code` | Same version as published, different code |
| `reg –` | Not in the registry |
| `fleet ✓n/m` | All m live agents run the published code |
| `fleet ▼k/m` | k live agents run older code. The operator page lists them by project. |
| `fleet ≠v×n` | No release is registered, and most peers run v |
| `run ✓` / `run ✕` | Running server matches disk / restart needed |

Live = active or idle and seen within `fleet_window_h` (default 12). The operator publishes with `harness.py publish <dir> --notes "…"` and watches `harness.py serve` → `/operator`.
