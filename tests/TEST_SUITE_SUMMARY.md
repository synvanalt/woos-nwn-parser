# Test Suite Summary - Woo's NWN Parser

**Last Updated:** March 16, 2026 (tooltip coverage and dark-theme tooltip outline refresh)

## Overview
This document reflects the current state of the `tests/` directory after classifying former top-level tests into suite directories.

Collection baseline used for this update:
- Command: `pytest --collect-only -qq tests -p no:cacheprovider`
- Result: **665 tests collected**

## Current Test Layout

- `tests/unit/`: 38 modules, 616 tests
- `tests/integration/`: 7 modules, 42 tests
- `tests/e2e/`: 1 module, 7 tests
- Total: 46 test modules, 665 tests

Notes:
- All active `test_*.py` files are now under `unit/`, `integration/`, or `e2e/`.
- `tests/demo_game_restart.py` remains a helper/demo script and is not collected as a test module.
- Main-window monitoring tests now validate the background monitor thread flow and lightweight UI tick behavior.

## Module Inventory

### Unit (`tests/unit`)
- `test_bump_version_script.py` (6)
- `test_models.py` (56)
- `test_parser.py` (73)
- `test_parser_model_formatter_p2.py` (5)
- `test_platform_wrappers_p2.py` (8)
- `test_storage.py` (61)
- `test_storage_indices.py` (21)
- `test_utils.py` (39)
- `test_monitor.py` (23)
- `test_monitor_debug_mode.py` (9)
- `test_queue_processor_unit.py` (36)
- `test_queue_processor_batched.py` (10)
- `test_queue_processor.py` (10)
- `test_dps_service.py` (14)
- `test_formatters.py` (22)
- `test_immunity_panel_additional.py` (10)
- `test_immunity_panel_edge_cases.py` (9)
- `test_selection_preservation.py` (4)
- `test_dps_panel_incremental.py` (13)
- `test_immunity_panel_incremental.py` (6)
- `test_target_stats_panel_incremental.py` (11)
- `test_ui_optimizations.py` (19)
- `test_death_snippet_panel.py` (26)
- `test_debug_console_panel.py` (6)
- `test_main_window_load_parse.py` (23)
- `test_message_dialogs.py` (3)
- `test_settings.py` (9)
- `test_main_window_monitoring_switch.py` (7)
- `test_main_window_debug_tab_unlock.py` (5)
- `test_main_window_orchestration.py` (24)
- `test_monitor_edge_cases.py` (4)
- `test_queue_processor_resilience.py` (5)
- `test_realtime_backpressure.py` (2)
- `test_sorted_treeview_edge_cases.py` (7)
- `test_storage_edge_branches.py` (8)
- `test_tooltip_registration.py` (3)
- `test_tooltips.py` (3)
- `test_utils_worker_pipeline.py` (14)

### Integration (`tests/integration`)
- `test_parser_storage_integration.py` (15)
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
  - Includes malformed timestamp fallback coverage, invalid calendar/numeric timestamp parsing, malformed target-concealed fast-path fallback coverage, parser output contracts for store-owned AC/AB/save derivation, whitespace-heavy multi-word damage-breakdown coverage, hot-path regression coverage for threat-roll/basic attack fast paths plus `+`-prefixed ability chains, and explicit AC/AB regression coverage for duplicate-hit invalidation and higher-bonus tie winners
- Storage and indexing performance behavior:
  - `test_storage.py`, `test_storage_indices.py`
  - Direct store setup now uses the real public batch API (`DataStore.apply_mutations(...)`) instead of legacy per-write helper methods
  - Includes explicit coverage for version-scoped read-cache invalidation, clear-all reset invalidation of cached target summaries, defensive-copy behavior on cached summary getters, raw-history retention default/normalization behavior, and store-summary suppression of temporary zero-damage-only full-immunity samples after later positive same-type damage
- Queue processor logic and batching:
  - `test_queue_processor.py`, `test_queue_processor_unit.py`, `test_queue_processor_batched.py`, `test_realtime_backpressure.py`
- Queue/import tests validate the public-first mutation payload flow used by production ingestion
  - Includes shared-matcher resilience coverage for reverse-order immunity lines, nearest-match selection, mismatch debug logging, and disabled-mode verification that damage events no longer enqueue matcher work or trigger periodic stale cleanup
- Release/version automation:
  - `test_bump_version_script.py`
- Monitor behavior (rotation/truncation/debug):
  - `test_monitor.py`, `test_monitor_debug_mode.py`, `test_monitor_edge_cases.py`, `test_log_rotation.py`, `test_file_truncation.py`, `test_monitor_parser_integration.py`, `test_integration_real_scenario.py`, `test_final_verification.py`
  - Includes steady-state active-file cache coverage, idle fallback rescans when directory metadata does not surface rotation immediately, and delayed discovery when monitoring starts before any NWN log file exists
- DPS service/pipeline:
  - `test_dps_service.py`, `test_dps_pipeline_integration.py`
- UI widget/main-window behavior and refresh optimizations:
  - `test_dps_panel_incremental.py`, `test_immunity_panel_incremental.py`, `test_target_stats_panel_incremental.py`, `test_ui_optimizations.py`, `test_main_window_load_parse.py`, `test_main_window_monitoring_switch.py`, `test_main_window_debug_tab_unlock.py`, `test_main_window_orchestration.py`, `test_message_dialogs.py`, `test_realtime_backpressure.py`, `test_selection_preservation.py`, `test_death_snippet_panel.py`, `test_formatters.py`
  - Includes explicit coverage for DPS, Target Stats, and Target Immunities no-op refresh short-circuiting, authoritative natural-order row moves, tree-sort scan bypass when callers already control order, and Target Stats staying empty after Clear Data-style store clears
  - Includes main-window orchestration coverage for single-read target-list fanout and panel refresh coordination, plus regression coverage that full tree rebuilds do not reapply sort more than necessary
  - Includes browse-directory coverage for `File` label fallback to `N/A`, active-file selection from the newest NWN log, monitor rebinding when the user changes directories mid-session, and retention of the last known filename when monitoring is paused
  - Includes dark modal dialog coverage for app-owned warning popups and bottom-right action-row alignment shared by warning and import-progress modals
  - Includes shared tooltip-manager coverage for delayed show/hide behavior, popup reuse, overwrite-safe registration, and first-pass tooltip wiring on the main window plus DPS, Target Immunities, Death Snippets, and Debug controls
  - Includes import payload application coverage for batched mutation submission on the Tk thread while preserving death-snippet delivery, death-character auto-identification, and queue-drain lifecycle behavior
  - Includes Death Snippets coverage for guarded `wooparseme` auto-identification and one-click character-name clearing back to the hint state
  - Includes dedicated realtime backlog coverage for bounded queue saturation, post-read monitor backpressure pacing, pressure-banded Tk drain budgets, and coalesced refresh behavior under producer-faster-than-consumer load
  - Includes Target Immunities coverage for zero-damage matched samples, absorbed-value tie-breaking, suppression of invalidated temporary full-immunity rows back to real max-damage display, best-effort immunity % display when exact reverse inference fails, and persisted/default-on Parse Immunities toggle behavior
- App settings persistence:
  - `test_settings.py`
  - Includes persisted `Parse Immunities` and `First Timestamp` coverage, including missing-key and invalid-value fallback behavior for older settings files
- Main-window persistence orchestration:
  - `test_main_window_load_parse.py`, `test_main_window_orchestration.py`
  - Includes startup restoration of persisted `First Timestamp` mode into the DPS service/UI, save scheduling on combobox changes, and session-settings serialization of the active timing mode
- Import/worker pipeline behavior:
  - `test_utils.py`, `test_utils_worker_pipeline.py`
  - Includes streaming chunk payload integrity, direct parse-to-chunk worker coverage, queue-full abort responsiveness coverage, import payload coverage after removing legacy parser-state snapshots, preserved `wooparseme` identity events during manual import, shared immunity-matcher parity for both damage-before-immunity and immunity-before-damage logs, and explicit disabled-mode coverage that import parsing does not construct the matcher when `Parse Immunities` is off
- Full-session/e2e behavior:
  - `test_e2e_combat_session.py`

## Shared Fixtures (`tests/conftest.py`)

Current shared fixtures include:
- `cleanup_tkinter` (autouse)
- `cleanup_persisted_app_settings` (autouse)
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
