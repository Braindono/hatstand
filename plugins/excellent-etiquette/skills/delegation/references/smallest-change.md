# delegation: the smallest-change ladder (phase 1)

Adapted from DietrichGebert/ponytail (MIT), phase 1, 2026-11-09. The idea of a ladder of options comes from that repository; the wording is ours. Pick the simplest solution that works, but never shortcut what the change must do: P-112's never-cut list still holds.

## The ladder (climb in order, stop at the first rung that works)
1. Needed at all? Drop the change if nothing breaks without it.
2. Already in the repo? Reuse it.
3. Language or platform built-in or standard library? Use that.
4. A package we already depend on? Use it; add no new dependency.
5. One line or one command? Prefer it.
6. Otherwise write the minimum that works; nothing speculative.

## Bug fixes: callers first
Search every caller of the code before changing it. Fix the root cause once, so no caller is left on the old behavior.

## Review checklist additions (our Blockers-first format stays)
- Lean pass: look for what to delete, reuse, or replace with a built-in.
- Cost of skipping: each finding says what it costs if left as it is.

Tracked source: the research-lead polls the ponytail repository for changes to what we took.
