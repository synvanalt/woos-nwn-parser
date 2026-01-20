# Changelog

## [1.1.0] - 2026-01-20

### Added
- **Column Sorting** - All treeviews now support sortable columns via header clicks
  - Click any column header to sort ascending/descending
  - Visual indicators (↑ ascending, ↓ descending) show current sort state
  - Intelligent type detection (numeric vs string) for optimal sorting
  - Sort preferences persist during data updates
  - Handles formatted numbers (percentages, commas, decimals)
  - New `SortedTreeview` widget component (`app/ui/widgets/sorted_treeview.py`)

### Changed
- **Target Stats Panel** - Unknown AB and AC values now display as "-" instead of "?" for consistency
- **Attack Bonus Tracking** - Now tracks the most common AB value (mode) instead of maximum to better represent typical attack bonus
  - Filters out temporary buffs/debuffs that previously skewed the max AB value
  - Example: Enemy with mostly +71 AB and occasional +77 buff now correctly shows +71
  - In case of tie frequency, prefers the higher bonus value
- **Performance Optimizations** - Implemented 9 major optimizations across all application layers:
  - **Parser**: Pre-compiled regex patterns (6-31% faster)
  - **Storage**: O(1) caches for targets and damage dealers (95-99% faster lookups)
  - **Storage**: O(1) indices for attacks/events by attacker/target
  - **Storage**: Single-pass counting for attack stats (10-40% faster)
  - **Monitor**: Optional debug_mode flag (saves 42k+ queue operations per 21k lines)
  - **Models**: Added `__slots__` to dataclasses (20-30% memory reduction)
  - **Queue Processor**: Batched UI callbacks (O(n) → O(1) per poll cycle)
  - **DPS Panel**: Incremental tree refresh (30-50% faster UI updates)
- **UI Panels** - All panels now use `SortedTreeview` instead of `ttk.Treeview`
  - DPS Panel with hierarchical parent/child structure
  - Target Stats Panel for target statistics
  - Immunity Panel for damage type immunities
- **Sort Persistence** - Optimized to only re-sort when necessary
  - Skips sorting if user hasn't interacted with sort headers
  - Applies sort only after structural changes (new items added/removed)
  - Reduces unnecessary O(n log n) operations during rapid updates

### Fixed
- **Timestamp Parsing** - Fixed incorrect elapsed time calculation when gameplay crosses midnight
  - Previously, timestamps only parsed the time portion (HH:MM:SS) and applied it to today's date
  - Now uses efficient manual parsing to extract the full date (month and day) from log timestamps
- **AC Estimation** - Natural 20 hits are now properly excluded from AC estimation (like natural-1 misses)
  - Previously, a natural 20 hit could incorrectly lower the estimated minimum AC
  - This reduces the occurrence of "~" (approximation) symbol in AC estimates
- **AC Estimation** - Hits against flat-footed targets are now automatically discarded
  - Tracks all hit totals (AB+d20 roll) instead of just the minimum
  - When a miss total exceeds recorded hits, those hits are discarded as invalid
  - This correctly handles temporary AC debuffs (flat-footed, blinded, etc.)
  - Example: If target was flat-footed (hit at 35), then recovered (miss at 42), the hit at 35 is discarded
  - Further reduces "~" approximation occurrences and shows true AC estimates
- **AC Estimation** - Attacks miss due to concealment are now excluded from AC estimation
  - Attacks that miss due to concealment (displacement, improved invisibility, etc.) don't reveal AC information
  - These misses had incorrect high totals that would have hit if not for concealment
  - Excluding them provides much more accurate AC estimates
  - Added 5 comprehensive tests to prevent regression
- `Reset Data` button now reverts the "Filter Target" dropdown to "All" after resetting


## [1.0.3] - 2026-01-13

### Changed
- **Global mode** now uses the last damage timestamp instead of continuously ticking with current time
  - Both "Global" and "Per Character" modes now use the same last timestamp (most recent damage by any character)
  - The only difference between modes is the start time: Global uses the earliest damage event, Per Character uses each character's first damage event
- Renamed "Time Tracking" label to "First Timestamp" for better clarity
- Renamed "By Character" option to "Per Character" for more accurate grammar

### Fixed
- Reverted DPS panel refreshing every 1 second when in "Global" mode (no longer needed)
- Reverted DPS tracking "Per Character" taking `last timestamp` per character (optimal behavior is to track only first timestamp)


## [1.0.2] - 2026-01-12

### Fixed
- DPS tracking "By Character" was tracking last damage event timestamp for all characters (correct behavior is to track timestamp per character)

### Changed
- DPS panel now refreshes automatically every 1 second when in "Global" time tracking mode


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
