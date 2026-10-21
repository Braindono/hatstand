# Backend status: INTERIM, flagged for replacement

| | |
|---|---|
| Current backend | `filesystem-jsonl`: one hash-chained `~/Claude/Projects/Exchange/_harness/events.jsonl` guarded by an advisory `flock` |
| Status | **INTERIM.** Approved as the easiest path to a working system. Not the long-term design. |
| Flag locations | `BACKEND_STATUS` in `scripts/harness.py`, the MCP server `instructions`, every ledger result, and the dashboard header badge |

## Why it will be replaced

1. **Reach.** Only agents that can see the folder can take part: Claude Code, and Cowork on this Mac. claude.ai web/mobile and other machines cannot.
2. **Locking.** `flock` is advisory and may not hold across the Cowork VM mount, network shares, or synced folders (iCloud, Dropbox). Concurrent writers there can fork the chain. `verify` detects forks but cannot prevent them.
3. **Scale.** Every read replays the full log, O(n). That is comfortable up to roughly 10,000 events, and then it slows.
4. **Latency.** Inbox long-polling watches the file's mtime every 200 ms. That is fine locally but is not push delivery.

## What stays when it is replaced

- The **MCP tool contract** (`harness_*` tools). Agents will not notice the swap.
- The **event format**: `seq`, `ts`, `type`, `actor`, `data`, `prev`, `hash`. An existing log can be replayed into any new backend as-is.
- The **projection logic** (`State`) and the **dashboard**.

## Replacement contract

A new backend implements three methods and is passed to `Harness(store=…)`:

```python
class Store:
    def append(self, etype: str, actor: str, data: dict) -> dict: ...  # atomic; sets seq/ts/t/prev/hash
    def read_all(self) -> list[dict]: ...                               # ordered by seq
    def changed_since(self, marker) -> tuple[bool, marker]: ...         # cheap change detection for long-poll
```

The candidates (local SQLite MCP, NATS JetStream, Cloudflare Durable Object) are explained separately.

## Migration

```
python3 scripts/harness.py export --out migrate.jsonl
python3 scripts/harness.py verify           # must be ok=true before migrating
# new backend: replay migrate.jsonl in seq order, preserving hashes; verify the head hash matches
```
