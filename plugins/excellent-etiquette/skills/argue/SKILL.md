---
name: argue
description: 'Use when: /argue [topic]; the operator wants a committee debate of options before deciding.'
---

# argue

`/argue <topic>`. Seats: domain expert, skeptic, divergent thinker, philosopher, mathematician, creative designer, engineer.
- Default cheap mode: one pass, no subagents.
  1. Round 1: one position per seat (<=2 lines).
  2. Round 2: one-line rebuttals.
  3. Chair synthesis table: option | backed by | main risk | token cost | confidence (green/yellow/white words per P-09).
  4. One "insight" sentence; one recommendation (P-02).
- Seats must disagree where they honestly would; facts are looked up, not invented.
- Total <=350 words.
- `/argue deep`: one Sonnet subagent per seat, in parallel; cost ~7x, say so first.
- End with AskUserQuestion only if the operator must choose.
