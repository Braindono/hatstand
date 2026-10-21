---
name: review
description: Human review (dashboard, traces, chain verify, export). Use for "open the dashboard", "audit".
---

# Human review

The source of truth is `_harness/events.jsonl` in the shared folder. It is an append-only log where every event carries the SHA-256 of the event before it.

## Live dashboard

Run the dashboard server locally. It needs a shell on the machine that holds the shared folder:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" serve --port 7717
```

Then tell the user to open http://127.0.0.1:7717. It refreshes every 2 seconds and has four tabs:
- **Ledger:** agent cards with lineage, expertise and unread counts.
- **Threads:** a message tree per thread, showing branch points, revisits (loops) and task states.
- **Leases & versions:** active leases and the full version history.
- **Event log:** every event with its hash link, plus a chain-verified badge.

The server blocks while it runs, so start it in the background (`… serve &`) or tell the user to run it themselves in a terminal.

If no long-running process is possible (e.g. Cowork), write a static snapshot:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/harness.py" dashboard
```

This writes `_harness/dashboard.html` in the shared folder. Tell the user the file name.

## Raw export and verification

- `harness_admin` op=`export` writes a timestamped JSONL copy to `_harness/export/` and returns the head hash. Report the path and the head hash.
- `harness_admin` op=`verify` recomputes the chain. If `ok=false`, list each problem (edited event, reordered or forked chain, corrupt line) with its sequence number. Forks usually mean two writers bypassed the lock, which is a known limit of the interim backend.

## Tracing

- For one conversation, call `harness_admin` op=`thread` args `{thread}` and render it as an indented tree: `hop`, from → to, kind, one-line gist, and task state.
- For "what did agent X do", filter the export or the dashboard's event log by actor.
- Summaries use compressed, structured bullets. Quote message bodies only when asked.
