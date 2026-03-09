---
name: release-docs-maintenance
description: Keep this project's release-facing documentation in sync with code changes. Use when coding agent updates CHANGELOG.md for end users, decides whether tests/TEST_SUITE_SUMMARY.md needs refresh after test changes, or performs repo tasks where release-note and test-summary maintenance should be handled consistently.
---

# Release Docs Maintenance

Use this skill to decide whether `CHANGELOG.md` and `tests/TEST_SUITE_SUMMARY.md` need updates for the current task.

## Update `tests/TEST_SUITE_SUMMARY.md`

Update `tests/TEST_SUITE_SUMMARY.md` only when the change set modifies existing tests under `tests/` or adds new test files.

Do not update it for:
- application-only code changes
- documentation-only changes
- benchmark-only changes
- helper/demo changes that do not affect collected tests

Treat `tests/demo_game_restart.py` as a helper/demo script, not part of the collected suite, unless the repo changes its role.

When you update the summary:
- keep the document aligned with the current collected suite state
- refresh only the sections affected by the test changes
- update counts, module inventory, coverage notes, fixture references, and the `Last Updated` note only as needed
- avoid churn in unrelated sections

## Update `CHANGELOG.md`

Write changelog entries for end users, not programmers.

Add or update an `[Unreleased]` entry when the task changes shipped behavior in a way users can notice, including:
- fixes
- UI or workflow changes
- persistence changes
- monitoring or import behavior changes
- meaningful performance improvements users can feel

Do not add entries for:
- internal refactors with no visible behavior change
- test-only changes
- maintenance work that users will never notice

When you write changelog text:
- describe the user-visible outcome
- avoid file names, module names, internal architecture terms, and implementation detail unless the user would understand and care
- keep the wording concise and consistent with the existing changelog tone
- place entries under the appropriate `[Unreleased]` subsection instead of creating a new release section

## Final Check

Before finishing:
- if no tests changed, leave `tests/TEST_SUITE_SUMMARY.md` untouched
- if no user-visible product behavior changed, leave `CHANGELOG.md` untouched
- if both conditions are false, update both documents in the same task
