# Changelog


## [1.0.1] - 2026-01-11

### Added
- Comprehensive test suite
- `README.md` file with app screenshots

### Fixed
- **Target Immunities** panel - coupled `Max Damage` and `Absorbed` (record both from same action) for accurate `Immunity %` calculation
- **Damage Per Second** panel - fixed treeview expand/collapse indicator not changing when parent is expanded

### Changed
- Moved icon file to `assets/icons/` for better encapsulation
- Rebuilt app using `pyinstaller` with a self-built bootloader to reduce AVs false positives


## [1.0.0] - 2026-01-09

### Added
- Real-time combat log parsing
- DPS calculations with time tracking modes
- Damage type breakdown
- Target filtering
- Hit rate statistics
- AB, AC, Saves per target
- Damage immunities per target
