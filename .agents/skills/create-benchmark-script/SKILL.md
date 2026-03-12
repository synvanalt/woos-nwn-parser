---
name: create-benchmark-script
description: Create or update Python benchmark scripts under this project's `scripts/` directory. Use when Codex needs to benchmark parser, storage, queue/import, monitor, UI refresh, IPC, memory, or similar performance paths in this repo and should follow the existing fixture, reporting, and validation conventions.
---

# Create Benchmark Script

## Overview

Create focused benchmark scripts that match this repository's existing `scripts/benchmark_*.py` style.
Keep the benchmark deterministic, CLI-driven, and aligned with the real-fixture performance rules in the repo.

## Workflow

1. Define the benchmark target before writing code.
   Benchmark one subsystem or workload family at a time: parser hotspots, full import, monitor polling, UI refresh, read-refresh, IPC, or memory.
   Decide whether the script measures one path, compares variants inside one repo, or compares two repo roots.

2. Reuse the repo's benchmark conventions.
   Put the script in `scripts/` and name it `benchmark_<topic>.py`.
   Use the three default real fixtures unless the benchmark requires a different input shape:
   `tests/fixtures/real_flurry_conceal_epicdodge.txt`
   `tests/fixtures/real_deadwyrm_offhand_crit_mix.txt`
   `tests/fixtures/real_tod_risen_save_dense.txt`
   Add `from __future__ import annotations`, `argparse`, `Path`, and `perf_counter` by default.
   When importing app modules directly, bootstrap `REPO_ROOT` onto `sys.path` as in the existing benchmark scripts.
   Expose `--iterations` and `--warmups`. Add focused flags only when they change the workload meaningfully.

3. Measure repeated runs, not anecdotes.
   Time with `perf_counter()`.
   Use repeated measured runs plus warmups.
   Report median at minimum; include min/max and spread when useful.
   Use dataclasses for immutable fixture metadata and per-run results when the script has more than a couple of values.
   Fail loudly if an import or workload setup does not succeed.

4. Keep output compact and comparable.
   Print a short heading plus the iteration settings.
   Prefer a fixed-width table or similarly scannable text output.
   Include throughput or output-size counts when they help detect correctness drift.
   If comparing variants, keep the row schema identical across variants.

5. Preserve production behavior while benchmarking.
   Do not add benchmark-only shortcuts inside app code unless the task explicitly requires them.
   Avoid new hot-path scans over `DataStore.events` or `DataStore.attacks`.
   Preserve batched queue processing and avoid per-event UI refresh patterns.
   Keep parser behavior unchanged unless the task is intentionally measuring a parser change and includes regression coverage.

6. Validate the result.
   Run the new benchmark script with its default arguments at least once.
   If the work accompanies a meaningful performance change, also run `python scripts/benchmark_baseline.py` and report before/after medians.
   Run targeted tests for any touched application code or shared helpers.

## Choosing A Pattern

- Use the `benchmark_baseline.py` pattern for parser-only plus full-import timing on shared fixtures.
- Use the `benchmark_parser_hotspots.py` or `benchmark_ui_refresh.py` pattern for one focused subsystem inside a single repo checkout.
- Use the `benchmark_read_refresh.py` or `benchmark_import_ipc.py` pattern when comparing variants or repo roots and import isolation matters.
- Use `benchmark_import_ops_memory.py` as the reference shape for memory-focused work.

## Implementation Notes

- Keep helper functions private unless the script is intentionally reusable.
- Prefer small pure helpers for fixture counting, median/rate formatting, and variant setup.
- If a script imports app modules from alternate repo roots, clear and reload `app` modules explicitly before each binding load.
- If the benchmark needs correctness guards, compare output counts between variants and raise on mismatch instead of silently printing bad numbers.
- Keep type hints on new and changed functions.

## Resources

Read `references/benchmark-conventions.md` when you need:
- the exact default fixtures and repo rules
- examples of which existing benchmark script to copy structurally
- a concise checklist before finishing
