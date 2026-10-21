---
name: design-rules
description: "Use when: laying out resumes, letters, artifacts: headers, spacing, fonts, margins."
---

# design-rules

- [project:cv-management] P-65 No orphan or widow words in any layout; verify at the actual render.
- [project:cv-management] P-66 Favor two-column print layout and chunked vertical blocks over full-width lines.
- [project:cv-management] P-67 Render a layout fix first; propose only wording verified to work.
- [global] P-68 Header identical across all resume and letter templates; monogram opacity .3; change every active template in one pass (resume wins).
- [role:design-system] P-69 Spacing values whole pixels, never fractional; 4-6px ATS job-card gap acceptable.
- [role:design-system] P-70 Always use LucentDS tokens.css for color, type, theming in any artifact or visualization.
- [project:cv-management] P-71 Letter body font Roboto only (sole exemption to LucentDS type); header follows resume (Space Grotesk/Space Mono).
- [project:cv-management] P-72 Publish cover letters only from design-system's template; side-panel doc is for drafting and review.
- [project:cv-management] P-73 Letters export as one-page PDF, body a bit larger than 11.2px; pick margin variant that fills the page best: _m042/_m050/_m075/_m100 (D-2cd5a).
