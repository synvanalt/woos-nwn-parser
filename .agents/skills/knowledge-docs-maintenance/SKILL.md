---
name: knowledge-docs-maintenance
description: Keep this project's internal knowledge docs in sync with code changes. Use when coding agent updates docs under docs/knowledge/, moves architecture guidance out of README, or changes AGENTS.md guidance about architecture and behavior source-of-truth docs.
---

# Knowledge Docs Maintenance

Use this skill to decide whether internal engineering knowledge docs under `docs/knowledge/` and related agent guidance in `AGENTS.md` need updates for the current task.

This skill is for internal source-of-truth documentation, not release notes.
If a task also changes end-user-visible behavior or collected tests, use `release-docs-maintenance` alongside this skill.

## Update `docs/knowledge/*.md`

Update a knowledge doc when the change set affects internal architecture, behavioral rules, or source-of-truth guidance that engineers or agents rely on.

Common triggers:
- architecture or ownership changes across parser, monitor, storage, services, query services, controllers, or widgets
- runtime flow changes, especially when data moves differently through the app
- changes to documented behavior rules such as immunity matching semantics or live/import parity expectations
- moving internal documentation out of `README.md` or changing which document is the primary architecture reference
- introducing a new knowledge doc or retiring an old one

Do not update knowledge docs for:
- test-only changes with no architecture or behavior impact
- changelog-only or release-note work
- benchmark-only changes unless they change the documented architecture or operational guidance
- minor wording cleanup in user-facing docs that does not affect internal guidance

When you update a knowledge doc:
- keep it aligned with the current code and actual ownership boundaries
- prefer source-of-truth summaries over long duplicated prose
- update only the affected sections instead of rewriting unrelated areas
- keep architecture docs focused on structure, data flow, boundaries, and behavioral invariants

## Update `AGENTS.md`

Update `AGENTS.md` when a task changes which internal doc agents should use as the source of truth, or when the high-level architecture bullets have become stale.

Typical triggers:
- a new or renamed file under `docs/knowledge/`
- a moved architecture reference
- changed guidance about which doc to consult for specific subsystems or behaviors
- stale architecture bullets that no longer match the current app shape

Do not update `AGENTS.md` for routine code changes when its guidance still points to the right docs.

## Relationship with `README.md`

`README.md` is product-facing. Update it here only when it should point to or lightly summarize a knowledge doc.
Do not turn the README back into the primary place for detailed internal architecture unless the repo intentionally changes that policy.

## Final Check

Before finishing:
- if runtime structure or behavioral guidance changed, verify the relevant `docs/knowledge/*.md` file matches the code
- if a knowledge-doc source of truth moved or was added, verify `AGENTS.md` points to it
- if only internal docs changed, leave `CHANGELOG.md` untouched unless user-visible behavior also changed
