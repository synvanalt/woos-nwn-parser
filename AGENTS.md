# AGENTS.md

## Purpose
- Windows Tk app for parsing Neverwinter Nights combat logs and showing DPS, target stats, immunities, and death snippets.

## Architecture
- `app/parser.py`: stable parser entrypoint for parser-facing consumers.
- `app/line_parser.py`: pure line parsing and event extraction implementation.
- `app/parser_session.py`: parser session state, line numbering, year inference, and death-correlation orchestration.
- `app/monitor.py`: log polling, rotation, and truncation handling.
- `app/storage.py`: in-memory session store with indexed mutable state and batched mutations.
- `app/services/event_ingestion.py`: shared parsed-event normalization into store mutations and side events.
- `app/services/immunity_matcher.py`: shared live/import damage-immunity correlation logic.
- `app/services/queue_processor.py`: batched queue draining and data-store writes.
- `app/services/queries/`: read-side query services for DPS, target summaries, and immunity summaries.
- `app/ui/runtime_config.py`: runtime tuning and app-shell policy defaults.
- `app/ui/tree_refresh.py`: shared tree refresh/diff logic for heavy table widgets.
- `app/ui/controllers/`: monitoring, import, refresh, settings, queue-drain, and debug-unlock orchestration.
- `app/ui/presenters/`: pure render-preparation helpers for widget-facing display data.
- `app/ui/`: Tk composition and panel wiring.
- `app/utils.py`: historic log import and worker-side parsing helpers.

## Knowledge Docs
- `docs/knowledge/architecture.md`: read when you need architecture context, runtime data flow, component ownership, or cross-component integration guidance. This is the architecture source of truth; keep `AGENTS.md` as the shorter operational summary.
- `docs/knowledge/immunity-matching.md`: read before changing immunity parsing, matcher heuristics, live/import parity, or `Target Immunities` panel calculation semantics.

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

