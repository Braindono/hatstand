---
name: ledger
description: Harness agents, inbox, file holders, identity. Use for "list agents", "my inbox", "/whoami".
---

# Ledger views

Every call returns compact pre-rendered text. Show it as-is; don't reformat it or add JSON.

| Request | Call |
|---|---|
| Agents | `harness_admin` op=`ledger` (args `{active_only:false}` for history) |
| Inbox | `harness_inbox`. When only peeking, use CLI `inbox --peek`, or report what you already have without re-reading. |
| Files | `harness_admin` op=`status`, args `{path}` |
| Who am I (`/whoami`) | `harness_admin` op=`whoami` with `agent`; reply with the banner verbatim, nothing else |
| Who works on X | Match X against the roles in the ledger, then `harness_recall` query=X for related decisions. |
