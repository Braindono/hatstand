# hatstand

A multi-agent harness for long-lived Claude work: a hash-chained event ledger, a decision corpus, durable roles, an MCP server, and the plugins that carry the protocol.

- `plugins/crew-coordinator`: the harness core (`scripts/harness.py`, `scripts/mcp_server.py`, `scripts/corpus.py`, hooks, skills, tests).
- `plugins/delegation-desk`, `excellent-etiquette`, `pixel-pilot`, `plugin-publications`: role, delegation, operator-preference, design and release skills.
- `.claude-plugin/marketplace.json`: the local marketplace manifest.
- `docs/harness-technical-overview.md`: what problem this solves, how it works, and what is novel.

Not included: the live ledger (`events.jsonl`), the decision corpus, registry and operator config. These are runtime data, not source. Pure Python 3.8+ standard library; no dependencies.
