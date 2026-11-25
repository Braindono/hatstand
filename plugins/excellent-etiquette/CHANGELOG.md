# Changelog

## 0.3.1 (2026-11-25): retired skills removed
Scope items (verbatim):
- Remove the five retired skills (autonomy, communication, continuity, index, laconic) from the plugin; their pointer bodies hold no rules, which live in CORE.md and the role files
- Plugin docs: version 0.3.1; CHANGELOG lists each scope item verbatim and names the five removed skills; README skill table drops their row

Removed: skills/autonomy, skills/communication, skills/continuity, skills/index, skills/laconic. Each held one pointer line to the rule files (CORE.md, the role files, INDEX.md in Exchange/rules/). Copies are kept in the repo under _archive/excellent-etiquette-0.3.0-retired-skills/. Operator order 11-25 via the secretary (m-37ee2106a9ef): fewer skills loaded at every agent start. Scope A-5f941.

## 0.3.0 (2026-11-13): rules moved to the rule files
Scope items (verbatim):
- Retired skills (communication, autonomy, continuity, laconic, index): each body becomes one pointer line to the rule files; descriptions say they hold no rules; their references are removed
- P-98 (skills/communication): the computer:// link rule is removed; where files go is the CORE rule: send the file or an artifact card, a path only as a secondary note
- Shared docs (skills/continuity/references/shared-docs.md): moved into the rules folder as a tier-3 file named in INDEX.md; the reference file is removed from the plugin
- Trimmed skills (delegation, plugins, cv-writing, design-rules): lines repeating CORE.md or a role file are dropped; model tiers and polling follow CORE.md; no record ids; descriptions cite CORE.md
- Old role names (skills/plugins, continuity): corpus-envoy and corpus-steward become envoy and steward in any line that survives
- Commands kept (argue, song, swarm): argue and song unchanged; swarm's packet sizes and report length follow CORE.md and delegation; citations point to the rule files; dead paths removed
- Plugin docs (CHANGELOG.md, README.md, plugin.json): version 0.3.0; the CHANGELOG lists every scope item verbatim and names the retired skills; README says rules moved to CORE.md

Notes:
- Retired (now one pointer line each): communication, autonomy, continuity, laconic, index. Their rules live in CORE.md and roles/<role>.md; the plugin's reference files for them are removed.
- Trimmed: delegation (4 lines dropped), plugins (9), cv-writing (2, the filename-prefix line is untouched), design-rules (4). Domain detail that the rules index names stays. Six clauses that the rule files do not carry (release checks, shared-repo adoption, Haiku packets, polished-prose stop, monogram opacity, ATS gap) were kept as one-line detail.
- /argue and /swarm: citations of retired rules now point to the rule files and the dead Harness_Router path is removed (behaviour unchanged); /swarm reports in chat as CORE.md and the role file allow.
- delegation: Opus tier replaced by 'only where a role file or his words say so'; Haiku first for mechanical work (CORE.md); a packet over 2 files is split or given to Sonnet.
- Record ids removed from the skill text; the pointer lines name CORE.md, the role files and INDEX.md.
- The 'corpus-envoy' and 'corpus-steward' names no longer appear (item 5: the lines that used them were retired or dropped).
- Uninstalling the retired skills is the operator's later step; this release only turns them into pointers.

## 0.2.15 (2026-11-13): laconic covers all output
Scope items (verbatim):
- Laconic skill (skills/laconic/SKILL.md): all output of envoy, curator, ops-coder, steward; no mail exemption, no work narration; chat to him at most 3 lines; critic, secretary, design-system exempt

Ships alone, at the operator's request (his words: "Laconic language should be updated immediately."; "Publish the ee plugin update first."), as an override of the 7-day cycle. Agent mail is as long as it needs to be; detail comes on "elaborate". Other etiquette drafts wait for the next regular release.

## 0.2.14 (2026-11-11): operator rules in the skills, path scrub
Scope items (verbatim):
- Scrub (communication and continuity references/more.md, cv-writing/SKILL.md, CHANGELOG.md): no user name, full name, home path or workspace path ships; the 0.24 hatstand guard passes
- Operator steps (communication and autonomy SKILL.md): his steps go to role:secretary's Hub queue, dry run first, not asked in a role's chat; if he asks in a chat, answer there and log it
- Step write-ups (skills/autonomy/SKILL.md): each install or settings step for the operator gets a full Hub write-up (what, why, before/after, risk, steps, check, undo); secretary alerts him
- Sandbox block (skills/autonomy/SKILL.md): a blocked shell command is not retried outside the sandbox; mail role:secretary kind=task: role, blocked host or path, purpose, work stopped or not
- Tables (skills/communication/SKILL.md): every table shown to the operator starts with a column of A-Z or 0-9 row labels, one scheme per table, kept stable when the table is shown again
- Explain, don't point (skills/plugins/SKILL.md): plugin code, docs and runtime text state the rule and its reason in words, never a record id; ids go only in private commit messages

Ships with crew-coordinator 0.24.0. The new rules are written in words, with no rule number and no record id.

## 0.2.13 (2026-11-09)
Scope (operator-approved, record A-5bdd3, 11-09; replaces A-d7cad and A-0e3d1): Communication skill: never hand the operator bare codes (R1-R14, W45, hk3); say it in words, with where and how to answer; code in parentheses; one example; Delegation skill: one line, do not sit idle over 5 minutes while helpers work (prompt cache); one static model-routing table (Haiku, Sonnet, Opus), under 150 tokens; P-111 amended (D-90d53): an idea the operator tells you is mailed once to role:secretary and recorded kind=note tags=[idea] the same turn; recall first, skip if already noted; work never waits; Ponytail phase 1, own words: six-rung smallest-change ladder in delegation/references/smallest-change.md plus a pointer line; callers-first line; lean pass and cost-of-skipping line in the review checklist; One line in the plugins skill (D-9d5a7): a shared repo is inspected, adapted not installed, in phases; CHANGELOG and reference header credit DietrichGebert/ponytail (MIT); Meaning-preserving tightening of the existing lines listed in the spec, no rule dropped, only to fit 600 tokens; P-99, P-102, P-103 untouched; the critic checks each clause by script; Stop rule: a critic blocker gets one fix round; a dropped clause in round 2 drops the tightening and ships 0.2.13 without the codes rule and the P-111 amendment; bodies stay under 600 tokens
- Communication skill: never hand the operator bare codes (R1-R14, W45, hk3); say it in words, with where and how to answer; code in parentheses; one example
- Delegation skill: one line, do not sit idle over 5 minutes while helpers work (prompt cache); one static model-routing table (Haiku, Sonnet, Opus), under 150 tokens
- P-111 amended (D-90d53): an idea the operator tells you is mailed once to role:secretary and recorded kind=note tags=[idea] the same turn; recall first, skip if already noted; work never waits
- Ponytail phase 1, own words: six-rung smallest-change ladder in delegation/references/smallest-change.md plus a pointer line; callers-first line; lean pass and cost-of-skipping line in the review checklist
- One line in the plugins skill (D-9d5a7): a shared repo is inspected, adapted not installed, in phases; CHANGELOG and reference header credit DietrichGebert/ponytail (MIT)
- Meaning-preserving tightening of the existing lines listed in the spec, no rule dropped, only to fit 600 tokens; P-99, P-102, P-103 untouched; the critic checks each clause by script
- Stop rule: a critic blocker gets one fix round; a dropped clause in round 2 drops the tightening and ships 0.2.13 without the codes rule and the P-111 amendment; bodies stay under 600 tokens
- Communication skill: the no-bare-codes rule is folded into P-04 (operator standing rule 11-09 via the secretary, m-4c441c36f11d): never show ids or bare codes (R1-R14, W45, hk3) alone; say it in words, with where and how to answer; code in parentheses; the example is in references/more.md. Critic round 1 on an earlier cut: P-99, P-102 and P-103 stay whole in the body.
- Delegation skill: P-114 (do not sit idle past 5 minutes while helpers run, the prompt cache expires; end the turn if nothing is left; P-42 still bars polling; hopper ta3), P-115 (a static model-tier table; vendor router savings are unverified; unless the operator set another model, and any steward model change passes the evals first, D-2a291; hopper ta5), P-116 (pointer: climb the smallest-change ladder, callers first on bug fixes, lean pass and cost of skipping in reviews).
- New reference skills/delegation/references/smallest-change.md: the six-rung ladder, callers first, the two review-checklist additions (our Blockers-first format stays). Adapted from DietrichGebert/ponytail (MIT), phase 1: the ladder idea from that repository, the wording ours (P-112's never-cut list, published in 0.2.12, also follows ponytail); plan projects/orchestration/specs/2026-11-09_ponytail-adaptation-plan.md. Later phases (shortcut convention, read-only debt script, trial audit) are not in this release.
- Continuity skill: P-111 amended per D-90d53 (it covers an idea you propose and one the operator tells you; the latter is mailed once to role:secretary; recall first, skip if already noted; work never waits for dispatch). The 0.2.12 clause "the secretary assigns its id" is dropped: the secretary assigns the id at triage whether or not the rule says so.
- Plugins skill: P-117 (a shared GitHub repo is inspected in code, adapted in phases, never installed by default, credited in the CHANGELOG; D-9d5a7). The index maps P-114 to P-116 to delegation and P-117 to plugins.
- Tightening (communication and continuity, to stay under 600 tokens): the existing lines listed in specs/2026-11-09_ee0213-tightened-lines.md were reworded with every clause kept (communication P-01, P-02, P-03, P-05, P-06, P-07, P-96, P-100; continuity P-45, P-46, P-50, P-52, P-53, P-101 pointer, P-104, P-105, P-110). Critic round 1 fixes: P-96 keeps "you raise", the P-101 pointer keeps "full text"; P-99, P-102 and P-103 are untouched. Bodies by the lint count: communication 599.25, continuity 599.25.
- Laconic: no change. README skill table rows updated.

## 0.2.12 (2026-11-09)
Scope (operator-approved, record A-cac58, 11-09; replaces A-154e5): Continuity skill: one rule line, an agent that proposes an idea records it the same turn with harness_record kind=note tags=[idea]; Delegation skill: one rule under 150 tokens, build only what the task needs, never cut validation, error handling, security or accessibility, then one review pass; no new skill; Nothing else changes; the rest of the idea backlog (scan, JSON fields, Hub view) needs no plugin release; Stop rule: a missed measure or critic blocker gets one fix round; two rounds in a row, the envoy re-scopes
- Continuity skill: one rule line, an agent that proposes an idea records it the same turn with harness_record kind=note tags=[idea]
- Delegation skill: one rule under 150 tokens, build only what the task needs, never cut validation, error handling, security or accessibility, then one review pass; no new skill
- Nothing else changes; the rest of the idea backlog (scan, JSON fields, Hub view) needs no plugin release
- Stop rule: a missed measure or critic blocker gets one fix round; two rounds in a row, the envoy re-scopes
- Continuity skill: new P-111 (an agent that proposes an idea records it the same turn with harness_record kind=note tags=[idea]; the secretary assigns its id). Critic fix round: an earlier cut said "propose or hear", which went beyond the grant; heard ideas are not covered. Design: 2026-11-05_idea-backlog-design-scope.md, critic Blockers 0. The index maps P-111 to continuity.
- Delegation skill: new P-112 (build only what the task needs, never cut validation, error handling, security or accessibility checks or the tests the task names, one review pass of your own diff that does not replace the critic's review; from the hopper item ta2, research ADAPT 10-29). Rule text is about 55 words. No new skill; the index maps P-112 to delegation.
- continuity body held at <=600 tokens: P-101 full text moved verbatim to skills/continuity/references/more.md; the body keeps one summary line for it.
- README skill table: delegation and continuity rows list the new rules.

## 0.2.11 (2026-11-05)
Scope (operator-approved, record A-89967, ruling 11-05): Add skill laconic: reply-shaping rules in our own words, body under 600 tokens; nothing else changes; No copied dictionary, no web lookups, no 80 percent rule; the package stays uninstalled; Mail between agents keeps its reason field; warm talk exempt; operator can say full detail; Critic measures one week: replies 25 percent shorter, reasons kept 18 of 20, no extra re-asks; Stop rule: a missed measure gets one rewrite round; two misses in a row drop the skill
- Add skill laconic: reply-shaping rules in our own words, body under 600 tokens; nothing else changes
- No copied dictionary, no web lookups, no 80 percent rule; the package stays uninstalled
- Mail between agents keeps its reason field; warm talk exempt; operator can say full detail
- Critic measures one week: replies 25 percent shorter, reasons kept 18 of 20, no extra re-asks
- Stop rule: a missed measure gets one rewrite round; two misses in a row drop the skill

## 0.2.10 (2026-10-30)
Scope (operator-approved, D-6385f and D-e7e43, record A-dae49; replaces A-9bec9 and A-96eab): autonomy skill: self-report rule (D-f83f8 H4): on your own miss, mail role:secretary unprompted with what happened, the cause and the fix; Shared Claude Doc rules (D-8a505, D-74864, D-a8292): one doc per multi-agent document, with status and Members tables; rationale and rebuttal comments; check your access first; design-rules skill: assume more than one design system (D-3f44f); P-70 and P-71 name no single system as the default
- autonomy skill: self-report rule (D-f83f8 H4): new P-109 in skills/autonomy/SKILL.md, text from the envoy (m-3131ac98d4ef), shortened to one line; the index maps P-109 to autonomy.
- Shared Claude Doc rules (D-8a505, D-74864, D-a8292): new P-110 in skills/continuity/SKILL.md (summary line), full text in the new skills/continuity/references/shared-docs.md; the index maps P-110 to continuity.
- design-rules skill: assume more than one design system (D-3f44f); P-70 and P-71 name no single system as the default: P-70 now reads "use the tokens file of the design system assigned to the project or artifact (e.g. LucentDS tokens.css)"; P-71's letter-font exemption is from "the assigned design system's type".
- autonomy body held at <=600 tokens: P-109 and P-85 full text moved verbatim to skills/autonomy/references/more.md; the body keeps one trigger-summary line for each.

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
- continuity P-101 (lowercase-with-dashes project folders; harness-ops/projects/<project>/ after the 2026-10-14 cutover).
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
