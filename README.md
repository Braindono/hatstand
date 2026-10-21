# hatstand

A multi-agent harness for long-lived Claude work: a hash-chained event ledger, a decision corpus, durable roles, an MCP server, and the plugins that carry the protocol.

- `plugins/crew-coordinator`: the harness core (`scripts/harness.py`, `scripts/mcp_server.py`, `scripts/corpus.py`, hooks, skills, tests).
- `plugins/delegation-desk`, `excellent-etiquette`, `pixel-pilot`, `plugin-publications`: role, delegation, operator-preference, design and release skills.
- `.claude-plugin/marketplace.json`: the local marketplace manifest.
- `docs/harness-technical-overview.md`: what problem this solves, how it works, and what is novel.

## Quick start (macOS or Linux)

```bash
git clone https://github.com/Braindono/hatstand.git && cd hatstand
./setup.sh --link --test      # creates the shared folder, config, ~/.local/bin/harness; runs the tests
```

`setup.sh` checks for Python 3.8+ and SQLite FTS5, creates the shared folder (default `~/Claude/Projects/Exchange`, or `--home PATH`), writes the default config there, and prints the remaining steps: add this repo as a Claude Code marketplace (`/plugin marketplace add <repo path>`), install the plugins from `harness-local`, and set `HARNESS_HOME`. It never overwrites existing config or data, and can be re-run. `bin/harness` is the CLI launcher (`harness roster`, `harness serve`, `harness pending`, `harness approve <id>`); `bin/wake.py` is the pass-the-ball wake registry. `config.example.json` shows the settings you can override.

Known gap: three tests in the crew-coordinator suite depend on files outside this repo (the corpus indexer and its pin, and a project digests folder), so they fail on a clean checkout; of 325 tests, 321 pass and 1 is skipped.

Not included: the live ledger (`events.jsonl`), the decision corpus, registry and operator config. These are runtime data, not source. Pure Python 3.8+ standard library; no dependencies.
