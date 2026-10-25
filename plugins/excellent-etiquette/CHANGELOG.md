# Changelog

## 0.2.9 (2026-10-24)
Scope (operator-approved, D-fffe6, record A-d8b95): R-064 operator preferences in skill text; R-067 flag-it definition in skill text; R-066 lessons rule in skill text; R-044 second reviewer rule for the final ACCEPT; R-057 release cadence rule text
- R-064 operator preferences in skill text: communication P-99 amended (dry run alone first, one command per id for prompting commands, paste with a leading !; replaces "join several with &&"), P-102 skepticism and gauge not guesses, P-103 a named tool describes the goal and a better way is always offered (D-24743, D-1aeb7, D-40d27, L-010, L-011).
- R-067 flag-it definition in skill text: continuity P-104 (record in corpus and register, tag for the next build, notify owner roles).
- R-066 lessons rule in skill text: continuity P-105 (add to docs/lessons.md, record with tag lesson, send to role:curator); plugins P-106 (curator folds lessons into skill text each release; L-005, L-006, L-007, L-008 rules).
- R-044 second reviewer rule for the final ACCEPT: plugins P-107 (second reviewer from another model family; canary to one role first when practical).
- R-057 release cadence rule text: plugins P-108 (one release per plugin per cycle chosen by the operator; hotfix only with his approval).
- communication body held at <=600 tokens: P-97 and P-98 detail moved verbatim to skills/communication/references/more.md, trigger summaries kept in the body.

## 0.2.8 (2026-10-23)
Scope (operator-approved, W43 E1): Autonomy P-80 and P-81 release-scope rule
- Autonomy P-80 and P-81 release-scope rule: release scope (items, version numbers, splitting, deferring, bundling) is the operator's decision; propose it with context and rationale, then wait; builders and the curator never cut, split or renumber a release on their own (D-5221b, D-dc75c).
- autonomy body held at <=600 tokens: P-91 and P-94 full text moved verbatim to skills/autonomy/references/more.md; the body keeps one trigger-summary line for both. Wording trimmed without changing any rule: merged-id cross-references (P-83, P-86, P-89, P-90; the index still maps them) removed, and P-82, P-81, P-88, P-92 tightened.

## 0.2.7 (2026-10-20)
- communication P-98 (computer:// markdown links for local paths), P-99 (operator commands in one fenced block, one line), P-100 (one status line while waiting on an agent).
- autonomy P-17 extended: routine agent-to-agent correspondence needs no operator prompt (D-c9982).
- continuity P-101 (lowercase-with-dashes project folders; ~/Claude/Code/harness-ops/projects/<project>/ after the 2026-10-14 cutover).
- index lists P-98..P-101; "Remember this" path now harness-ops/projects/skill-curation/review/etiquette-inventory.md.

## 0.2.6 (2026-10-08)
- communication P-96 (suggestion + default on open questions; pending list proceeds) and P-97 (questionnaire for multi-action tables, daily checklist, action-items folder).
- delegation P-40: Haiku first, Sonnet fallback only after failed proof or spawn denial; log failures.

## 0.2.5 (2026-10-08)
- autonomy trimmed to <=600 tokens (P-81/83, P-85/86, P-87/89, P-21/90 merged; ids kept in index).
- P-82 gains review_by + expiry default (reversible only).
- P-94 mail-check cadence (rule 33). P-95 secretary questionnaire auto-build (scoped).

## 0.2.4 (2026-10-08)
- autonomy P-91: operator reminders are sent to role:secretary as REMIND rows for the action-item table. Index lists P-88..P-93.
- autonomy P-92 (resume: pending list, inbox, work) and P-93 (remember-this notifies skill-curation-lead).

## 0.2.3 (2026-10-08)
- autonomy P-90: pending build action proceeds automatically; publish still waits for envoy ACCEPT naming the sha. Index lists P-88..P-90.

## 0.2.2 (2026-10-08)
- autonomy P-88: act on corpus-check and lint WARNs yourself; send reviews to the owner role, never ask the operator (D-1e728).
- autonomy P-89: reply to waiting mail on init/restore, then check harness_inbox routinely.
- Inventory backfilled with P-80..P-87 (plus P-88, P-89); README inventory path fixed.

## 0.2.1 (2026-10-07)
- autonomy P-87: mail needing an answer says "reply immediately"; sender long-polls its inbox itself. Envoy-scoped P-18/P-23 moved to references/scoped.md (600-token cap).

## 0.2.0 (2026-10-07)
- autonomy: P-80..P-86 (quiet operator, agent mail never routed to operator, digest batching, better-path and naming prompts).
- New skills: swarm (with references/dependencies.md), argue, song.

## 0.1.1 (2026-10-07)
- Fix: index skill description had nested double quotes (invalid YAML); plugin failed to load. Now single-quoted.
## 0.1.0 (2026-10-07)
- Initial build from etiquette-inventory (79 rows; 74 active across 8 skills).
