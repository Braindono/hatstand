# CLI fallback

Use the CLI when the MCP tools are not available but a shell is. It has the same semantics and writes to the same log.

```
H="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/harness.py"     # or the absolute path shown in the banner context
$H register --project <name> --expertise "…" [--task "…"] [--successor-of <id>] [--confirmed]
$H expertise --agent <id> --expertise "…" [--task "…"]
$H whoami --agent <id>
$H ledger [--active]
$H send --agent <id> --to <who> --body "…" [--subject …] [--kind task] [--reply-to <msg>] [--ref <path>]… [--max-hops N] [--expects-reply]
$H inbox --agent <id> [--wait 30] [--peek] [--all]
$H thread <thread-id>
$H task --agent <id> <msg-id> working|completed|failed|input-required|canceled|rejected [--note …]
$H claim --agent <id> <path> [--ttl 900] [--intent "…"]
$H commit --agent <id> <path> --base <version> [--note "…"]
$H release --agent <id> [<path>]
$H status [<path>]
$H group --agent <id> <name> [--leave]
$H retire --agent <id|operator> [--target <id>]
$H roster [--project P] [--since SEQ]
$H role-define <role> --project P [--owns GLOB]… [--partner ROLE]… [--carry none]
$H role-assign <role> [--target <id>]
$H set-project --agent <id|operator> --target <id> --project <name>
$H update --agent <id> [--ctx N] [--full] [--dry-run] [--verbose]
$H send --agent operator --to <id|*> --body "…"   # operator → agents
$H inbox --agent operator             # messages sent to the operator
$H init                               # create config.json + OPERATOR.md
$H record --agent <id> --kind decision|context|capsule|note --title "…" [--body …|--body-file f] [--tag t]… [--supersedes ID] [--offload]
$H recall ["query"] [--kind k] [--tag t] [--limit 5] | recall --ids D-xxxxx,K-yyyyy [--budget 1500]
$H publish [plugin-or-skill-dir] --notes "…" [--required]   # release registry (operator)
$H registry
$H verify | export [--out file] | events [--since N]
$H serve [--port 7717]       # live dashboard; /operator = chats needing action
$H dashboard [--out file]    # static snapshot
```

Shared folder: `$HARNESS_HOME`. If that is unset, the CLI uses the first existing of `~/Claude/Projects/Exchange` and `~/mnt/Exchange` It never falls back to another folder; if neither exists, it returns an error. Project folders whose files agents claim go under `"workspaces"` in `Exchange/_harness/config.json`, or in `$HARNESS_WORKSPACES`, separated by colons.

Output is compact text. Set `HARNESS_JSON=1` for JSON.

CLI fallback form: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" <cmd> --agent <short>`.

## Fuller protocol wording (moved from SKILL.md)

Longer forms of rules that SKILL.md states in short form.

- Identity: with MCP register, show the banner. Hook sessions: the app shows it, so don't repeat it. Pass its short id as `agent` everywhere. No banner: `harness_register project= model=<id>` first. A successor or resumed chat runs `/update` first.
- `superseded by …`: stop; another chat holds your role (new chat: `/restore <role>`). Load only the tools you call.
- Corpus: `decision` is a binding choice. Event ids (m-/t-/#N/actor) return event cards from recall. Recall/inbox output over 10k chars is cut to head+tail 5k. Docs live in `Exchange/corpus/` (auto-indexed).
- State note: on hook "State changed", add `state_note=` (≤1200 chars, `Next: … | Open: … | Verified: … | Chat: …`) to your next send/commit/sync/handoff.
- Messaging: `harness_inbox` `wait` is in seconds (≤60). `to` accepts a sobriquet as well as an id. When the loop guard refuses a send, send `operator` a `question`. Keep bodies short. Set task states with `harness_admin op=task_update`.
- Shared files: `granted:false` means don't edit; message the holder. `drift:true`: re-read first.
- Closing out: release leases, send `handoff`/`result`, write a capsule if work continues, and set task states. When the user says done: `harness_admin op=retire`.
