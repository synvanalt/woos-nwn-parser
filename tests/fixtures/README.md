# Test Fixtures

This directory contains real and synthetic NWN log fixtures used by tests and benchmarks.

## Files

### real_flurry_conceal_epicdodge.txt
- **Purpose:** Dense mixed-combat coverage (flurry, concealment, threat-roll variants, death fallback snippet)

### real_deadwyrm_offhand_crit_mix.txt
- **Purpose:** High-volume mixed boss encounters with off-hand attacks, high critical traffic, and broad event diversity

### real_tod_risen_save_dense.txt
- **Purpose:** Save-heavy scenario with strong immunity/attack mix and Epic Dodge examples

### synthetic_parser_variety_matrix.txt
- **Type:** Synthetic curated fixture assembled from representative lines across different logs
- **Purpose:** Compact edge-case matrix for parser variety coverage in one file
- **Note:** `Pure` immunity absorb lines were not found in corpus, so this fixture includes `Pure` damage but not a `Pure` immunity line

## Using Test Fixtures

Shared fixtures from `tests/conftest.py`:
- `real_combat_log` -> `real_flurry_conceal_epicdodge.txt`
- `real_combat_log2` -> `real_deadwyrm_offhand_crit_mix.txt`
- `real_combat_log3` -> `real_tod_risen_save_dense.txt`
- `synthetic_combat_log` -> `synthetic_parser_variety_matrix.txt`

Example:

```python
def test_with_real_log(real_combat_log: Path):
    parser = LogParser()
    with open(real_combat_log, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parser.parse_line(line)
```

