# Changelog

## 0.4.1 (2026-10-14)
- Republished as a verified package with a marketplace directory; no content change.

## 0.4.0 (2026-10-06)
- Renamed from agent-delegation (D-b2c05).
## 0.3.0
- publish-cycle and listings-feed moved to parsed-job-data 0.2.0 (D-35506).


## 0.2.5
- delegate description ≤100 chars.

## 0.2.4
- Skill descriptions trimmed to ≤100 chars (were 186–197).


## 0.2.3

- C1 (D-b9225): `whoami` skill moved to harness-router 0.9.0 (`/harness-router:whoami`).

## 0.2.2
- New `whoami` skill: /whoami prints the agent's Harness identity banner via `harness_admin op=whoami`, verbatim.

## 0.2.1
- listings-feed: skips postings by URL when a file for that URL already exists, without reopening them (saves ~3–5k tokens per known posting); skips the manifest and send when nothing is new; after sending, fires letters-manager's wake (pass the ball). Runs are manual only (operator, 2026-09-24): no scheduled task.

## 0.2.0
- roles: "Pass the ball" section. A waiting role creates one wake (`send_later`, 7-day fallback), records it in `Exchange/_harness/wake.json` via `_harness/wake.py`, and ends its turn. The finisher sends its result to `role:<r>`, then fires that wake. Waiting costs 0 tokens; there's no polling and no timed check-ins. Examples use project slugs (D-de1ff).

## 0.1.1
- listings-feed reads `listings_dir` from `Exchange/projects/cv-management/PROJECT.md`. roles: added a project-cards section. Other projects' claude.ai instructions can't be read, so cards replace them for cross-project rules.

## 0.1.0
- Skills: `delegate` (subagent dispatch rules), `roles` (role addressing, roster, ownership), `publish-cycle` (resume/letter publication tickets), `listings-feed` (stateless crawl → manifest → letters-manager). Skills only; ticket state lives in harness-router 0.6.0 ops (D-68eae).
