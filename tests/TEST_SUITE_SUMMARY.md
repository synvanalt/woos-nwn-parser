# Test Suite Summary - Woo's NWN Parser

**Last Updated:** March 28, 2026 (session 5 UI/runtime-config coverage refresh)

## Overview
This document reflects the current state of the `tests/` directory after the Session 5 UI decomposition cleanup and a fresh full-suite recollection.

Collection baseline used for this update:
- Command: `python -m pytest --collect-only -qq tests -p no:cacheprovider`
- Result: **686 tests collected**

## Current Test Layout

- `tests/unit/`: 43 modules, 635 tests
- `tests/integration/`: 7 modules, 44 tests
- `tests/e2e/`: 1 module, 7 tests
- Total: 51 test modules, 686 tests

Notes:
- All active `test_*.py` files are under `unit/`, `integration/`, or `e2e/`.
- `tests/demo_game_restart.py` remains a helper/demo script and is not collected as a test module.
- Main-window workflow coverage is now split between app-shell orchestration tests and focused controller/runtime-policy tests.

## Module Inventory

### Unit (`tests/unit`)
- `test_bump_version_script.py` (6)
- `test_death_snippet_panel.py` (15)
- `test_death_snippet_presenter.py` (13)
- `test_debug_console_panel.py` (6)
- `test_dps_panel_incremental.py` (14)
- `test_dps_query_service.py` (16)
- `test_formatters.py` (22)
- `test_immunity_panel_additional.py` (10)
- `test_immunity_panel_edge_cases.py` (9)
- `test_immunity_panel_incremental.py` (6)
- `test_immunity_query_service.py` (8)
- `test_main_window_debug_tab_unlock.py` (5)
- `test_main_window_load_parse.py` (22)
- `test_main_window_monitoring_switch.py` (8)
- `test_main_window_orchestration.py` (11)
- `test_message_dialogs.py` (3)
- `test_models.py` (56)
- `test_monitor.py` (23)
- `test_monitor_debug_mode.py` (9)
- `test_monitor_edge_cases.py` (4)
- `test_parser.py` (81)
- `test_parser_model_formatter_p2.py` (5)
- `test_platform_wrappers_p2.py` (8)
- `test_queue_processor.py` (10)
- `test_queue_processor_batched.py` (10)
- `test_queue_processor_resilience.py` (5)
- `test_queue_processor_unit.py` (36)
- `test_realtime_backpressure.py` (2)
- `test_refresh_coordinator.py` (2)
- `test_runtime_config.py` (1)
- `test_selection_preservation.py` (4)
- `test_session_settings_controller.py` (2)
- `test_settings.py` (9)
- `test_sorted_treeview_edge_cases.py` (7)
- `test_storage.py` (66)
- `test_storage_edge_branches.py` (8)
- `test_storage_indices.py` (21)
- `test_target_stats_panel_incremental.py` (11)
- `test_tooltip_registration.py` (3)
- `test_tooltips.py` (5)
- `test_ui_optimizations.py` (19)
- `test_utils.py` (39)
- `test_utils_worker_pipeline.py` (15)

### Integration (`tests/integration`)
- `test_dps_pipeline_integration.py` (10)
- `test_file_truncation.py` (2)
- `test_final_verification.py` (1)
- `test_integration_real_scenario.py` (1)
- `test_log_rotation.py` (5)
- `test_monitor_parser_integration.py` (10)
- `test_parser_storage_integration.py` (15)

### End-to-End (`tests/e2e`)
- `test_e2e_combat_session.py` (7)

## Coverage Areas by Component

- Parser and models:
  - `test_parser.py`, `test_models.py`, `test_parser_storage_integration.py`
  - Includes direct `LineParser` coverage for pure damage-breakdown parsing, explicit `ParserSession` coverage for year-rollover and death-correlation behavior, malformed timestamp fallback coverage, invalid calendar/numeric timestamp parsing, malformed target-concealed fast-path fallback coverage, parser output contracts for store-owned AC/AB/save derivation, hot-path regression coverage for threat-roll/basic attack fast paths plus `+`-prefixed ability chains, and explicit AC/AB regression coverage for duplicate-hit invalidation and higher-bonus tie winners
- Storage and indexing performance behavior:
  - `test_storage.py`, `test_storage_indices.py`
  - Direct store setup now uses the real public batch API (`DataStore.apply_mutations(...)`) instead of older per-write helper methods
  - Includes explicit coverage for version-scoped read-cache invalidation, clear-all reset invalidation of cached target summaries, immutable typed query-row behavior on cached summary getters, raw-history retention default/normalization behavior, store-summary suppression of temporary zero-damage-only full-immunity samples after later positive same-type damage, and atomic DPS projection snapshots that bundle timing state with indexed summaries
- Queue processor logic and batching:
  - `test_queue_processor.py`, `test_queue_processor_unit.py`, `test_queue_processor_batched.py`, `test_realtime_backpressure.py`
  - Queue/import tests validate the public-first mutation payload flow used by production ingestion
  - Includes direct `QueueDrainResult` assertions for DPS/target/immunity/death side effects instead of legacy callback fanout, plus shared-matcher resilience coverage for reverse-order immunity lines, nearest-match selection, mismatch debug logging, and disabled-mode verification that damage events no longer retain matcher-side state or trigger periodic stale cleanup
- Release/version automation:
  - `test_bump_version_script.py`
- Monitor behavior (rotation/truncation/debug):
  - `test_monitor.py`, `test_monitor_debug_mode.py`, `test_monitor_edge_cases.py`, `test_log_rotation.py`, `test_file_truncation.py`, `test_monitor_parser_integration.py`, `test_integration_real_scenario.py`, `test_final_verification.py`
  - Includes steady-state active-file cache coverage, idle fallback rescans when directory metadata does not surface rotation immediately, delayed discovery when monitoring starts before any NWN log file exists, and edge-case monitor tests that now use realistic `readline()`-driven file doubles instead of runtime test-only file-handle branches
- DPS query service/pipeline:
  - `test_dps_query_service.py`, `test_dps_pipeline_integration.py`
  - Includes direct coverage that DPS table rows and damage-type breakdowns consume one atomic store projection snapshot instead of stitching together timing and summary reads across multiple lock acquisitions
  - Query-service, integration, queue-processor, and e2e tests now consume typed DTO attributes directly instead of legacy dict-like row access
- Immunity query service/display preparation:
  - `test_immunity_query_service.py`
  - Includes direct coverage for prepared `Target Immunities` display rows, including zero-damage full absorbs, absorbed-value tie winners, temporary full-immunity suppression, best-effort reverse-immunity inference, parse-toggle remembered percentage display, same-version parse-off cache invalidation after a later parse-on read, and immutable cached row DTOs
- UI widget/main-window behavior and refresh optimizations:
  - `test_dps_panel_incremental.py`, `test_immunity_panel_incremental.py`, `test_target_stats_panel_incremental.py`, `test_ui_optimizations.py`, `test_main_window_load_parse.py`, `test_main_window_monitoring_switch.py`, `test_main_window_debug_tab_unlock.py`, `test_main_window_orchestration.py`, `test_refresh_coordinator.py`, `test_runtime_config.py`, `test_session_settings_controller.py`, `test_message_dialogs.py`, `test_realtime_backpressure.py`, `test_selection_preservation.py`, `test_death_snippet_panel.py`, `test_formatters.py`
  - Includes explicit coverage for DPS, Target Stats, and Target Immunities no-op refresh short-circuiting, authoritative natural-order row moves, tree-sort scan bypass when callers already control order, Target Stats staying empty after Clear Data-style store clears, and a DPS full-refresh regression guard that catches per-row rescans of the ordered DPS row list
  - Includes main-window orchestration coverage for target-list fanout, runtime-config-driven queue policy wiring, app-level delegation into controllers, and shutdown ordering across settings, import, monitor, storage, and tooltip teardown
  - Includes controller-first monitoring coverage for switch state, active-file label updates, deferred restart behavior, retained last-known filename when monitoring is paused, coalesced refresh scheduling, debounced session-settings persistence, and the hidden Debug Console unlock controller
  - Includes explicit coverage that heavy widgets use an explicit query-service fast-path capability flag instead of method-introspection compatibility shims
  - Includes dark modal dialog coverage for app-owned warning popups and bottom-right action-row alignment shared by warning and import-progress modals
  - Includes shared tooltip-manager coverage for delayed show/hide behavior, popup reuse, overwrite-safe registration, and first-pass tooltip wiring on the main window plus DPS, Target Immunities, Death Snippets, and Debug controls
  - Includes controller-first import coverage for modal layout, worker startup, incremental payload application, preserved death-snippet / death-character side-event delivery, and debug-toggle delegation through `MonitorController.set_debug_enabled(...)`
  - Includes Death Snippets widget coverage for selection state, placeholder behavior, Tk tag application, guarded `wooparseme` auto-identification, one-click character-name clearing back to the hint state, and wrap-toggle scroll preservation
  - Includes dedicated realtime backlog coverage for bounded queue saturation, post-read monitor backpressure pacing, pressure-banded Tk drain budgets, and coalesced refresh behavior under producer-faster-than-consumer load
  - Includes Target Immunities coverage for zero-damage matched samples, absorbed-value tie-breaking, suppression of invalidated temporary full-immunity rows back to real max-damage display, best-effort immunity % display when exact reverse inference fails, and persisted/default-on Parse Immunities toggle behavior
- Death Snippets presenter coverage:
  - `test_death_snippet_presenter.py`
  - Includes pure render-preparation coverage for chat-prefix sanitization, opponent extraction, wrap-mode line padding, damage/name span generation, per-render name-pattern cache reuse, and killed-name precedence over opponent highlighting
- App settings persistence:
  - `test_settings.py`
  - Includes persisted `Parse Immunities` and `First Timestamp` coverage, including missing-key and invalid-value fallback behavior for older settings files
- Main-window persistence orchestration:
  - `test_main_window_load_parse.py`, `test_main_window_orchestration.py`, `test_session_settings_controller.py`
  - Includes startup restoration of persisted `First Timestamp` mode into the DPS query service/UI, app-to-settings-controller delegation, save scheduling on combobox changes, and session-settings serialization of the active timing mode without app-shell cache mirroring
- Import/worker pipeline behavior:
  - `test_utils.py`, `test_utils_worker_pipeline.py`
  - Includes streaming chunk payload integrity, direct parse-to-chunk worker coverage, queue-full abort responsiveness coverage, import payload coverage after removing legacy parser-state snapshots, preserved `wooparseme` identity events during manual import, shared immunity-matcher parity for both damage-before-immunity and immunity-before-damage logs, explicit disabled-mode coverage that import parsing does not construct the matcher when `Parse Immunities` is off, and direct parity coverage that shared event ingestion stays aligned across the pure engine, live queue draining, and import payload generation
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
- `dps_query_service`
- `queue_processor`
- `temp_log_dir`
- `sample_log_lines`
- `sample_combat_session`
- `real_combat_log` -> `tests/fixtures/real_flurry_conceal_epicdodge.txt`
- `real_combat_log2` -> `tests/fixtures/real_deadwyrm_offhand_crit_mix.txt`
- `real_combat_log3` -> `tests/fixtures/real_tod_risen_save_dense.txt`
- `synthetic_combat_log` -> `tests/fixtures/synthetic_parser_variety_matrix.txt`

Notes:
- `tests/conftest.py` no longer monkeypatches removed `DataStore` write methods for tests.
- `temp_log_dir` now uses repo-local per-test directories under `.pytest_tmp` for more reliable file-based tests on Windows in this workspace.

## Shared Test Helpers

- `tests/helpers/store_mutations.py`
  - Provides shared builders for the public-first storage API, including `apply(...)`, `damage_row(...)`, `dps_update(...)`, `damage_dealt(...)`, `attack(...)`, `immunity(...)`, `save(...)`, and `epic_dodge(...)`.
  - Used by storage, panel, DPS query-service, and import-related tests to keep setup aligned with production mutation batching.
- `tests/helpers/parsed_event_factories.py`
  - Provides typed parsed-event builders for queue and ingestion tests, including damage, immunity, attack, save, and death-related events.
  - Keeps parsed-event fixtures aligned with the strict runtime dataclass contract without reintroducing dict-to-event compatibility shims.

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
