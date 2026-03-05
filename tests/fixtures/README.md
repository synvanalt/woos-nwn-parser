# Test Fixtures

This directory contains test data files for the test suite.

## Files

### nwclientLog1.txt
- **Size:** 405KB (4145 lines)
- **Type:** Real NWN combat log file
- **Purpose:** Available for integration/performance testing

This is a real combat log file extracted from Neverwinter Nights gameplay. It contains:
- Multiple combat encounters
- Various damage types (Physical, Fire, Cold, Acid, Electrical, Sonic, etc.)
- Damage immunity events
- Attack rolls (hits, misses, critical hits)
- Saving throws (Fortitude, Reflex, Will)
- Multiple characters and targets

### nwclientLog2.txt
- **Size:** 2.1MB (21772 lines)
- **Type:** Real NWN combat log file
- **Purpose:** Large-scale integration/performance testing and parser edge coverage

This is a larger real combat log file extracted from Neverwinter Nights gameplay. It contains:
- High-volume combat event traffic
- Damage immunity, resistance, and reduction absorb lines
- Attack and damage lines across many targets
- Saving throws, deaths, and mixed non-combat chat/system lines
- Useful stress cases for import worker and parser filtering behavior

## Using Test Fixtures

Test fixtures are automatically made available through `conftest.py`:

```python
def test_with_real_log(real_combat_log: Path):
    """Example test using the real combat log fixture."""
    parser = LogParser()
    
    with open(real_combat_log, 'r') as f:
        for line in f:
            result = parser.parse_line(line)
            # ... test logic
```

```python
def test_with_larger_real_log(real_combat_log2: Path):
    """Example test using the larger real combat log fixture."""
    assert real_combat_log2.name == "nwclientLog2.txt"
```

## Adding New Fixtures

When adding new test data files:

1. Place files in this `fixtures/` directory
2. Add a fixture in `conftest.py` to expose it
3. Document the fixture in `TEST_SUITE_SUMMARY.md`
4. Keep fixture files under 1MB when possible
5. Use descriptive names (e.g., `combat_with_immunities.txt`)

