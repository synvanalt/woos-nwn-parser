# Benchmark Conventions

## Repo Rules

- Use benchmark scripts only under `scripts/`.
- Use the default real fixtures unless the workload requires something else:
  - `tests/fixtures/real_flurry_conceal_epicdodge.txt`
  - `tests/fixtures/real_deadwyrm_offhand_crit_mix.txt`
  - `tests/fixtures/real_tod_risen_save_dense.txt`
- Benchmark both parser-only and full-import paths when the task changes parser or storage performance in a way that makes both layers relevant.
- Report actual median deltas before and after meaningful performance changes.
- Avoid full scans over `DataStore.events` or `DataStore.attacks` in hot paths.
- Prefer store-side indexed lookups over panel-side filtering or repeated aggregation.
- Preserve batched queue processing. Avoid per-event UI refreshes.

## Existing Script Map

- `scripts/benchmark_baseline.py`
  - Best starting point for fixture metadata, parser-only/full-import timing, adaptive iterations, and compact tables.
- `scripts/benchmark_parser_hotspots.py`
  - Use when splitting parser cost by line category or other internal bucket.
- `scripts/benchmark_monitor_polling.py`
  - Use when isolating monitor loop overhead from parser work.
- `scripts/benchmark_ui_refresh.py`
  - Use when importing once and repeatedly timing Tk panel/service refresh calls.
- `scripts/benchmark_read_refresh.py`
  - Use when comparing read-cache or service-refresh variants, including repo-root comparisons.
- `scripts/benchmark_import_ipc.py`
  - Use when measuring worker, queue, and consumer behavior for multiprocessing import.
- `scripts/benchmark_import_ops_memory.py`
  - Use when the target metric is memory instead of wall-clock time.

## Recommended Script Shape

1. Start with a one-line module docstring that states the workload.
2. Add `from __future__ import annotations`.
3. Add a `DEFAULT_FIXTURES` tuple of `Path(...)` values when fixtures are part of the benchmark.
4. Add small dataclasses for fixture metadata and measured results when the output has structure.
5. Parse CLI args with `argparse`.
6. Time repeated runs with `perf_counter()`.
7. Summarize with median and any supporting rates or counts needed for confidence.
8. Print output in a compact, diff-friendly text table.

## Validation Checklist

- Run the new script with defaults and confirm it completes successfully.
- Check that row counts or output sizes stay stable across compared variants when that matters.
- Run targeted tests for any touched app code.
- If the benchmark accompanies a real performance change, run `python scripts/benchmark_baseline.py` too and capture median before/after numbers.
