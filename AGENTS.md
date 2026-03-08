# AGENTS.md

## Purpose
- Windows Tk app for parsing Neverwinter Nights combat logs and showing DPS, target stats, immunities, and death snippets.

## Architecture
- `app/parser.py`: line parsing and event extraction.
- `app/monitor.py`: log polling, rotation, and truncation handling.
- `app/storage.py`: in-memory session store with indices and cached lookups.
- `app/services/queue_processor.py`: batched queue draining and data-store writes.
- `app/services/dps_service.py`: DPS and breakdown calculations.
- `app/ui/`: Tk orchestration and panel refresh logic.
- `app/utils.py`: historic log import and worker-side parsing helpers.

## Performance Rules
- Benchmark before and after meaningful performance changes with `python scripts/benchmark_baseline.py`.
- Use the default real fixture logs in benchmark scripts:
  `tests/fixtures/real_flurry_conceal_epicdodge.txt`,
  `tests/fixtures/real_deadwyrm_offhand_crit_mix.txt`,
  and `tests/fixtures/real_tod_risen_save_dense.txt`.
- Measure both parser-only and full-import paths. Improvements must report actual deltas.
- Avoid adding full scans over `DataStore.events` or `DataStore.attacks` in hot paths.
- Prefer store-side indexed lookups over panel-side filtering or repeated aggregation.
- Preserve batched queue processing. Avoid per-event UI refreshes.
- Treat `README.md` as secondary to code when architecture claims disagree.

## Change Rules
- Keep type hints on new and changed functions.
- Preserve parser behavior first; performance changes need regression coverage.
- When changing UI refresh logic, watch `DPSPanel`, `ImmunityPanel`, and `TargetStatsPanel` for churn.

## Validation
- Run targeted tests for touched areas.
- Re-run `python scripts/benchmark_baseline.py` after performance changes.
- Report benchmark median before/after, not just perceived speedups.
