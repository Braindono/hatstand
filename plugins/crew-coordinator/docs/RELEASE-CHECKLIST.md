# Release checklist (curator; lessons from 0.27.1, each cost a gate run)
Read by the curator before any release. Nothing here runs at runtime; tests/test_0272_matrix.py checks this file names every item below.

- **Gates command.** `specs/run_gates.py run <tree> --shards 4 --out gates-opseatNN` on the final commit; pins first.
- **release_sim command.** Run the release simulator from the INSTALLED plugin: `python3 -I -B <installed>/scripts/release_sim.py --candidate <release worktree> --gate-files <paths named in the scope> --report-dir <dir>`. It does not read the signed scope.
- **Release-questions answers change the package sha.** Answer every question in `release-questions.md` (it is in the package, so the answers change the package sha); answer before the package is built.
- **The "Gate file changed:" phrase.** The release gate reads scope items by regex: a changed gate file must appear as the exact phrase "Gate file changed: <path>" in a scope item (a changed gate function as "Gate file changed: <path>::<function>"), with no trailing period or other text, and the item text must appear in the CHANGELOG section (substring check, items 200 characters or fewer).
- **ACCEPT line starting rule.** The ACCEPT message must have a line that STARTS with "ACCEPT sha=<12 hex>"; a numbered or bulleted line fails.
- **Package built last.** Build the package last, from a clean release worktree; record the sha in DELIVERABLES.md; supersede old files into operator-scripts/_superseded with the sha in the name.
- **Scope request.** `harness_admin op=release_scope` (60 minutes to live); he signs with the one line. Publish lines go to the envoy: dry run first, `--operator-override` when inside the 7-day cadence.
- **Dated switches expire silently.** Run `python3 scripts/dated_switches.py check` before a release: it prints one line per config date within 14 days or past (observe periods in gates.json and config.json). Shipped code carries no switch date.
