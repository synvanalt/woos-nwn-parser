# Test Suite Documentation - Woo's NWN Parser

**Last Updated:** January 10, 2026  

## Overview
Comprehensive test suite for the Woo's NWN Parser application covering unit tests, integration tests, and end-to-end tests.

**Test Statistics:**
- Total Tests: 225
- Pass Rate: 100%
- Code Coverage: 54%
- Execution Time: ~5 seconds

## Quick Start

```bash
# Run all tests
pytest tests/unit tests/integration tests/e2e

# Run with coverage report
pytest tests/unit tests/integration tests/e2e --cov=app --cov-report=html

# Run specific test file
pytest tests/unit/test_parser.py -v

# Run tests matching a pattern
pytest -k "damage" -v
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and pytest configuration
├── unit/                    # Unit tests (146 tests)
│   ├── test_models.py       # Data model tests (35 tests)
│   ├── test_parser.py       # Log parser tests (36 tests)
│   ├── test_storage.py      # Data storage tests (44 tests)
│   ├── test_utils.py        # Utility function tests (22 tests)
│   ├── test_monitor.py      # File monitoring tests (20 tests)
│   └── test_queue_processor_unit.py  # Queue processor tests (27 tests) ✨ NEW
├── integration/             # Integration tests (67 tests)
│   ├── test_parser_storage_integration.py      # Parser + Storage (13 tests)
│   ├── test_monitor_parser_integration.py      # Monitor + Parser (9 tests)
│   └── test_dps_pipeline_integration.py        # Complete DPS pipeline (11 tests)
├── e2e/                     # End-to-end tests (7 tests)
│   └── test_e2e_combat_session.py              # Full combat sessions (7 tests)
└── fixtures/                # Test data and fixtures
    └── nwclientLog1_for_testing.txt  # Real 4145-line combat log (405KB)
```

### Test Fixtures

**conftest.py** provides shared fixtures:
- `parser`, `parser_with_immunity`, `parser_with_player` - LogParser instances
- `data_store` - DataStore instance
- `dps_service` - DPSCalculationService instance
- `queue_processor` - QueueProcessor instance
- `temp_log_dir` - Temporary directory for log files
- `sample_log_lines` - Dictionary of sample log lines for various scenarios
- `sample_combat_session` - Creates a synthetic combat session file
- `real_combat_log` - Path to real NWN combat log for performance/integration testing

## Coverage by Module

| Module | Coverage | Notes |
|--------|----------|-------|
| `app/models.py` | 100% | ✅ Fully tested |
| `app/parser.py` | 100% | ✅ Fully tested |
| `app/utils.py` | 100% | ✅ Fully tested |
| `app/services/dps_service.py` | 94% | ✅ Well tested |
| `app/services/queue_processor.py` | 92% | ✅ Well tested ⬆️ IMPROVED from 11% |
| `app/monitor.py` | 91% | ✅ Well tested |
| `app/storage.py` | 83% | ✅ Good coverage |
| `app/ui/*` | 0% | ℹ️ UI not tested (requires Tkinter mocking) |
| `app/__main__.py` | 0% | ℹ️ Entry point not tested |

## Test Categories

### Unit Tests (146 tests)

**test_models.py** - Tests for data models (35 tests)
- EnemySaves: initialization, save updates, max tracking
- EnemyAC: hit/miss recording, AC estimation, natural 1 handling
- TargetAttackBonus: bonus tracking, display formatting
- DamageEvent, AttackEvent: dataclass initialization
- DAMAGE_TYPE_PALETTE: color validation

**test_parser.py** - Tests for log parsing (36 tests)
- Initialization and configuration
- Damage breakdown parsing (single, multiple, multiword types)
- Timestamp extraction
- Damage dealt parsing with player filtering
- Immunity parsing (various point formats)
- Attack parsing (hit, miss, critical, natural 1)
- Save parsing (fortitude, reflex, will)
- Edge cases (empty lines, invalid input)

**test_storage.py** - Tests for data storage (44 tests)
- Initialization and data insertion
- DPS tracking and calculations
- Time tracking modes (by_character, global)
- Target filtering and queries
- Attack statistics and hit rates
- Immunity tracking
- Thread safety
- Data clearing

**test_utils.py** - Tests for utility functions (22 tests)
- Damage reduction calculations
- Reverse immunity calculations
- Immunity percentage calculations
- File parsing and import
- Edge cases and error handling

**test_monitor.py** - Tests for file monitoring (20 tests)
- File discovery (single, multiple files)
- Monitoring initialization
- Incremental reading
- File rotation detection
- File truncation detection (game restarts)
- Error handling

**test_queue_processor_unit.py** - Tests for queue processor (27 tests) ✨ NEW
- Event routing (damage, immunity, attacks, debug messages)
- Damage buffering and storage
- Immunity queuing and matching logic
- Cleanup of stale immunity entries
- DPS tracking integration
- Callback invocations
- Error handling and edge cases

### Integration Tests (67 tests)

**test_parser_storage_integration.py** - Parser and storage integration (13 tests)
- Damage event parsing and storage
- Immunity event matching
- Attack event tracking
- Save event tracking
- Complete combat session parsing
- Multi-word damage types
- DPS breakdown calculations
- Hit rate integration
- Target summaries

**test_monitor_parser_integration.py** - Monitor and parser integration (9 tests)
- Basic monitoring workflow
- File rotation scenarios (log1 → log2 → log3)
- Truncation detection and recovery
- Real-world scenarios (game start, play, restart)
- Multiple polling cycles

**test_dps_pipeline_integration.py** - Complete DPS pipeline (11 tests)
- Full pipeline (log → parse → storage → DPS service → output)
- Target filtering
- Time tracking modes
- Damage type breakdown
- Hit rate integration
- Multi-character and multi-target scenarios
- Immunity with DPS calculations

### End-to-End Tests (7 tests)

**test_e2e_combat_session.py** - Complete combat sessions (7 tests)
- Full party combat (4 characters vs 1 boss)
  - Verifies: damage, DPS, hit rates, AC, AB, saves, immunities
- Multi-target combat
- Complex immunity scenarios
- Edge cases (natural 1 misses)
- Time tracking mode comparisons
- Error recovery (malformed lines, empty files)

## Running Tests

### Run all tests
```bash
pytest tests/unit tests/integration tests/e2e -v
```

### Run with coverage
```bash
pytest tests/unit tests/integration tests/e2e --cov=app --cov-report=html
```

### Run specific test file
```bash
pytest tests/unit/test_parser.py -v
```

### Run specific test
```bash
pytest tests/unit/test_parser.py::TestDamageBreakdownParsing::test_parse_multiword_damage_types -v
```

## Test Quality Standards

All tests follow these standards:
- ✅ Use pytest framework and fixtures
- ✅ Include type hints for all function parameters and returns
- ✅ Use descriptive test names that explain what is being tested
- ✅ Test both success paths and failure modes
- ✅ Mock external dependencies (no real file I/O in unit tests)
- ✅ Validate both expected outputs and exception handling
- ✅ Cover edge cases and boundary conditions

## Recent Improvements (January 2026)

### Completed ✅
1. **Queue Processor Coverage** - Improved from 11% to 92%
   - Added 27 comprehensive unit tests in `test_queue_processor_unit.py`
   - Tested event routing, damage buffering, immunity queuing
   - Tested cleanup mechanisms and callbacks
   - Coverage increased by 81 percentage points

2. **Removed Obsolete Tests**
   - Deleted `old_tests_1/` directory (outdated `app_nwn_spy` imports)
   - Deleted `olds_tests_2/` directory (outdated `nwn_target_spy` imports)
   - Eliminated import errors and confusion

3. **Test Count Growth**
   - Increased from 198 to 225 tests (+27 tests, +14%)
   - Overall coverage improved from 46% to 54%
   - All tests passing (100% pass rate)

## Future Improvements

1. **Add UI tests** (currently 0%)
   - Consider using `pytest-tk` or mocking `tkinter`
   - Test widget behavior and user interactions
   - Test main window event handling

2. **Performance tests**
   - Test with very large log files (100K+ lines)
   - Measure parsing speed and memory usage
   - Optimize hot paths if needed

3. **Property-based tests**
   - Use `hypothesis` for property-based testing
   - Generate random valid log lines and verify parsing
   - Test edge cases automatically

## Common pytest Options

### Useful Flags
- `-v` or `--verbose`: Show each test name
- `-vv`: Extra verbose with parameters
- `-q` or `--quiet`: Minimal output
- `-x` or `--exitfirst`: Stop on first failure
- `--tb=short`: Short traceback format
- `-s`: Show print statements
- `--lf` or `--last-failed`: Run only failed tests
- `--cov-fail-under=70`: Fail if coverage below threshold

### Coverage Reports
```bash
# HTML report (open htmlcov/index.html)
pytest --cov=app --cov-report=html

# Terminal report with missing lines
pytest --cov=app --cov-report=term-missing

# XML report for CI
pytest --cov=app --cov-report=xml
```

## Maintenance

When adding new features:
1. Write tests first (TDD approach)
2. Ensure new code has ≥80% coverage
3. Run full test suite before committing
4. Update this summary if test structure changes

### Troubleshooting

**Import errors:**
```bash
# Ensure you're in the project root
cd C:\gdrive_avirams91\Code\Python\woos-nwn-parser
python -m pytest tests/unit tests/integration tests/e2e
```

**Pytest not found:**
```bash
pip install pytest pytest-cov
```

## Continuous Integration

Recommended CI setup:
```yaml
- Run tests on: push, pull_request
- Python versions: 3.12+
- Coverage threshold: 70% (aim for 80%+)
- Fail on: any test failure, coverage drop
```

