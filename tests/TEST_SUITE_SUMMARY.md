# Test Suite Summary - Woo's NWN Parser

**Last Updated:** March 9, 2026 (Public-first `DataStore` test migration and shared mutation helper update)

## Overview
This document reflects the current state of the `tests/` directory after classifying former top-level tests into suite directories.

Collection baseline used for this update:
- Command: `pytest --collect-only -qq tests -p no:cacheprovider`
- Result: **572 tests collected**

## Current Test Layout

- `tests/unit/`: 34 modules, 523 tests
- `tests/integration/`: 7 modules, 42 tests
- `tests/e2e/`: 1 module, 7 tests
- Total: 42 test modules, 572 tests

Notes:
- All active `test_*.py` files are now under `unit/`, `integration/`, or `e2e/`.
- `tests/demo_game_restart.py` remains a helper/demo script and is not collected as a test module.
- Main-window monitoring tests now validate the background monitor thread flow and lightweight UI tick behavior.

## Module Inventory

### Unit (`tests/unit`)
- `test_bump_version_script.py` (6)
- `test_models.py` (52)
- `test_parser.py` (72)
- `test_parser_model_formatter_p2.py` (5)
- `test_platform_wrappers_p2.py` (8)
- `test_storage.py` (47)
- `test_storage_indices.py` (21)
- `test_utils.py` (37)
- `test_monitor.py` (19)
- `test_monitor_debug_mode.py` (9)
- `test_queue_processor_unit.py` (33)
- `test_queue_processor_batched.py` (9)
- `test_queue_processor.py` (10)
- `test_dps_service.py` (14)
- `test_formatters.py` (22)
- `test_immunity_panel_additional.py` (5)
- `test_immunity_panel_edge_cases.py` (6)
- `test_selection_preservation.py` (4)
- `test_dps_panel_incremental.py` (11)
- `test_immunity_panel_incremental.py` (3)
- `test_target_stats_panel_incremental.py` (3)
- `test_ui_optimizations.py` (18)
- `test_death_snippet_panel.py` (24)
- `test_debug_console_panel.py` (6)
- `test_main_window_load_parse.py` (16)
- `test_settings.py` (5)
- `test_main_window_monitoring_switch.py` (5)
- `test_main_window_debug_tab_unlock.py` (5)
- `test_main_window_orchestration.py` (15)
- `test_monitor_edge_cases.py` (4)
- `test_queue_processor_resilience.py` (5)
- `test_sorted_treeview_edge_cases.py` (7)
- `test_storage_edge_branches.py` (8)
- `test_utils_worker_pipeline.py` (9)

### Integration (`tests/integration`)
- `test_parser_storage_integration.py` (13)
- `test_monitor_parser_integration.py` (10)
- `test_dps_pipeline_integration.py` (10)
- `test_file_truncation.py` (2)
- `test_log_rotation.py` (5)
- `test_integration_real_scenario.py` (1)
- `test_final_verification.py` (1)

### End-to-End (`tests/e2e`)
- `test_e2e_combat_session.py` (7)

## Coverage Areas by Component

- Parser and models:
  - `test_parser.py`, `test_models.py`, `test_parser_storage_integration.py`
  - Includes malformed timestamp fallback coverage, invalid calendar/numeric timestamp parsing, and malformed target-concealed fast-path fallback coverage
- Storage and indexing performance behavior:
  - `test_storage.py`, `test_storage_indices.py`
  - Direct store setup now uses the real public batch API (`DataStore.apply_mutations(...)`) instead of legacy per-write helper methods
- Queue processor logic and batching:
  - `test_queue_processor.py`, `test_queue_processor_unit.py`, `test_queue_processor_batched.py`
  - Queue/import tests validate the public-first mutation payload flow used by production ingestion
- Release/version automation:
  - `test_bump_version_script.py`
- Monitor behavior (rotation/truncation/debug):
  - `test_monitor.py`, `test_monitor_debug_mode.py`, `test_monitor_edge_cases.py`, `test_log_rotation.py`, `test_file_truncation.py`, `test_monitor_parser_integration.py`, `test_integration_real_scenario.py`, `test_final_verification.py`
- DPS service/pipeline:
  - `test_dps_service.py`, `test_dps_pipeline_integration.py`
- UI widget/main-window behavior and refresh optimizations:
  - `test_dps_panel_incremental.py`, `test_immunity_panel_incremental.py`, `test_target_stats_panel_incremental.py`, `test_ui_optimizations.py`, `test_main_window_load_parse.py`, `test_main_window_monitoring_switch.py`, `test_main_window_debug_tab_unlock.py`, `test_main_window_orchestration.py`, `test_selection_preservation.py`, `test_death_snippet_panel.py`, `test_formatters.py`
- App settings persistence:
  - `test_settings.py`
- Import/worker pipeline behavior:
  - `test_utils.py`, `test_utils_worker_pipeline.py`
  - Includes streaming chunk payload integrity and queue-full abort responsiveness coverage
- Full-session/e2e behavior:
  - `test_e2e_combat_session.py`

## Shared Fixtures (`tests/conftest.py`)

Current shared fixtures include:
- `cleanup_tkinter` (autouse)
- `shared_tk_root` (session)
- `log_capture`
- `parser`
- `parser_with_immunity`
- `parser_with_player`
- `data_store`
- `dps_service`
- `queue_processor`
- `temp_log_dir`
- `sample_log_lines`
- `sample_combat_session`
- `real_combat_log` -> `tests/fixtures/real_flurry_conceal_epicdodge.txt`
- `real_combat_log2` -> `tests/fixtures/real_deadwyrm_offhand_crit_mix.txt`
- `real_combat_log3` -> `tests/fixtures/real_tod_risen_save_dense.txt`
- `synthetic_combat_log` -> `tests/fixtures/synthetic_parser_variety_matrix.txt`

Notes:
- `tests/conftest.py` no longer monkeypatches removed legacy `DataStore` write methods for tests.
- `temp_log_dir` now uses repo-local per-test directories under `.pytest_tmp` for more reliable file-based tests on Windows in this workspace.

## Shared Test Helpers

- `tests/helpers/store_mutations.py`
  - Provides shared builders for the public-first storage API, including `apply(...)`, `damage_row(...)`, `dps_update(...)`, `damage_dealt(...)`, `attack(...)`, `immunity(...)`, `save(...)`, and `epic_dodge(...)`.
  - Used by storage, panel, DPS service, and import-related tests to keep setup aligned with production mutation batching.

## Fixture Files (`tests/fixtures`)

- `real_flurry_conceal_epicdodge.txt` (~1.2 MB)
- `real_deadwyrm_offhand_crit_mix.txt` (~2.4 MB)
- `real_tod_risen_save_dense.txt` (~1.5 MB)
- `synthetic_parser_variety_matrix.txt` (compact synthetic edge-case matrix)

See `tests/fixtures/README.md` for detailed fixture notes.

## Running Tests

Run all tests:

```bash
pytest
```

Equivalent explicit command:

```bash
pytest tests/unit tests/integration tests/e2e
```

Run without coverage overhead (useful for fast iteration):

```bash
pytest --no-cov
```

Run by suite type:

```bash
pytest tests/unit
pytest tests/integration
pytest tests/e2e
```

Run a specific module:

```bash
pytest tests/unit/test_parser.py -v
```

## Maintenance Guidance

When adding or moving tests:
1. Keep file names as `test_*.py` to ensure pytest discovery.
2. Place tests in `unit/`, `integration/`, or `e2e/` based on scope.
3. Update this summary and `tests/fixtures/README.md` when fixtures or shared fixtures change.
4. For performance-related parser/storage changes, run `python scripts/benchmark_baseline.py` with the default real fixtures and report before/after medians.
