# Test Suite Summary - Woo's NWN Parser

**Last Updated:** March 6, 2026

## Overview
This document reflects the current state of the `tests/` directory after classifying former top-level tests into suite directories.

Collection baseline used for this update:
- Command: `pytest --collect-only -q tests`
- Result: **428 tests collected**

## Current Test Layout

- `tests/unit/`: 21 modules, 379 tests
- `tests/integration/`: 7 modules, 42 tests
- `tests/e2e/`: 1 module, 7 tests
- Total: 29 test modules, 428 tests

Notes:
- All active `test_*.py` files are now under `unit/`, `integration/`, or `e2e/`.
- `tests/demo_game_restart.py` remains a helper/demo script and is not collected as a test module.

## Module Inventory

### Unit (`tests/unit`)
- `test_models.py` (52)
- `test_parser.py` (61)
- `test_storage.py` (40)
- `test_storage_indices.py` (19)
- `test_utils.py` (37)
- `test_monitor.py` (19)
- `test_monitor_debug_mode.py` (9)
- `test_queue_processor_unit.py` (28)
- `test_queue_processor_batched.py` (9)
- `test_queue_processor.py` (10)
- `test_dps_service.py` (13)
- `test_formatters.py` (22)
- `test_selection_preservation.py` (4)
- `test_dps_panel_incremental.py` (11)
- `test_immunity_panel_incremental.py` (3)
- `test_target_stats_panel_incremental.py` (3)
- `test_ui_optimizations.py` (18)
- `test_death_snippet_panel.py` (4)
- `test_main_window_load_parse.py` (7)
- `test_main_window_monitoring_switch.py` (5)
- `test_main_window_debug_tab_unlock.py` (5)

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
- Storage and indexing performance behavior:
  - `test_storage.py`, `test_storage_indices.py`
- Queue processor logic and batching:
  - `test_queue_processor.py`, `test_queue_processor_unit.py`, `test_queue_processor_batched.py`
- Monitor behavior (rotation/truncation/debug):
  - `test_monitor.py`, `test_monitor_debug_mode.py`, `test_log_rotation.py`, `test_file_truncation.py`, `test_monitor_parser_integration.py`, `test_integration_real_scenario.py`, `test_final_verification.py`
- DPS service/pipeline:
  - `test_dps_service.py`, `test_dps_pipeline_integration.py`
- UI widget/main-window behavior and refresh optimizations:
  - `test_dps_panel_incremental.py`, `test_immunity_panel_incremental.py`, `test_target_stats_panel_incremental.py`, `test_ui_optimizations.py`, `test_main_window_load_parse.py`, `test_main_window_monitoring_switch.py`, `test_main_window_debug_tab_unlock.py`, `test_selection_preservation.py`, `test_death_snippet_panel.py`, `test_formatters.py`
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
- `real_combat_log` -> `tests/fixtures/nwclientLog1.txt`
- `real_combat_log2` -> `tests/fixtures/nwclientLog2.txt`

## Fixture Files (`tests/fixtures`)

- `nwclientLog1.txt` (~405 KB, 4,145 lines)
- `nwclientLog2.txt` (~2.1 MB, 21,772 lines)

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
4. For performance-related parser/storage changes, run `python scripts/benchmark_baseline.py` with both fixture logs and report before/after medians.
