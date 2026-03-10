# Changelog

## [Unreleased]

### Changed
- Improved long-session responsiveness while keeping combat totals accurate across the session
- Combat event history now auto-limits in long sessions to keep memory use and responsiveness stable (oldest raw entries are removed first while summaries and totals stay intact)
- DPS damage-type breakdown updates are more efficient during active fights and target filtering
- Target AC and attack-bonus estimates now update more efficiently during heavy combat without changing displayed values
- Live monitoring now avoids repeated log-file rediscovery during steady polling while still detecting rotation and truncation safely
- Table refreshes now skip more no-op work and preserve default order more efficiently during active sessions
- Death snippet lookup on large logs is more efficient during backward scans
- Combat log timestamp handling is more resilient when a log line contains a malformed date or time
- `Load & Parse` import now checks abort requests more frequently and reports progress in steady intervals
- `Load & Parse` now applies large import batches in shorter UI time slices to reduce visible stutter during big imports
- `Load & Parse` now applies queued import updates in small batches per UI frame, which makes large imports feel smoother and finish UI updates faster
- `Load & Parse` import now uses safer queue flow control between background worker and UI to prevent excessive memory growth during very large imports
- `Load & Parse` and live monitoring now handle large batches of combat events more smoothly, reducing stutter during heavy activity
- Aborting `Load & Parse` now exits more reliably even under heavy import load
- Target lists and target summaries now refresh more efficiently in large encounters

### Fixed
- Fixed stale DataStore index retention that could cause avoidable long-session slowdowns
- Fixed stale-immunity cleanup timing when processed-event batches jump across cleanup boundaries
- Fixed DPS panel not refreshing after changing `First Timestamp` while monitoring is paused
- Fixed malformed timestamp and concealment attack lines being handled less safely than necessary during parsing


## [1.4.0] - 2026-03-07

### Changed
- Monitoring now stays smoother during heavy combat (less UI freezing and stuttering)
- Live log parsing now runs in the background to minimize UI interference
- The app now remembers your last selected log directory between launches
- The Death Snippets `Fallback Log Line` now persists between launches
- Death Snippets now server-agnostic:
  - You can auto-identify your character by whispering `wooparseme`
  - Death detection works either by your character name or by a fallback line (if character name is empty)
- Death Snippets usability improved:
  - `Killed by:` list selects and opens snippets directly (newest first)
  - Better log coloring for names, damage types, and damage values
  - New `Line Wrap` toggle for easier reading

### Fixed
- Fixed monitor edge cases around log file handling
- Fixed Death Snippets horizontal scrolling in no-wrap mode
- Fixed Death Snippets wrap toggle so it keeps your current reading position
- Improved table sorting consistency for numbers and special values (for example `-`, `≤`, `>`)

## [1.3.1] - 2026-03-04

### Changed
- Faster log parsing, especially on large combat logs and during file imports
- Smoother DPS, Target Stats, and Target Immunities panel refreshes during active sessions
- Better responsiveness when filtering DPS by a specific target
- Improved overall handling of large sessions to reduce slowdowns as more combat data accumulates


## [1.3.0] - 2026-02-27

### Added
- AC Estimation - added Epic Dodge detection from combat log lines to flag affected targets (unreliable estimation)
- New `Load & Parse` workflow for importing one or more selected `.txt` log files from disk (historical session analysis)
  - Abortable import modal with progress feedback for files parsed
- Hidden `Debug Console` unlock gesture: click the `Damage Per Second` tab title 7 times within 3 seconds to reveal
- New `Death Snippet` tab to capture post-death context:
  - Triggered only by `Your God refuses to hear your prayers!`
  - Looks back to the nearest prior `<Opponent> killed <Character>` line to identify the dead character
  - Appends up to 100 most recent lines related to that character
  - Works for both live monitoring and `Load & Parse` imports
  - Multiple deaths can be recorded and will have text separators for isolation

### Changed
- AC estimates now show a `~` prefix for targets detected with Epic Dodge to indicate the value may be skewed by guaranteed first-attack evasion each round
- Optimized AC estimation hit discarding logic by adding a short-circuit check against `min_hit`
- Replaced the separate `Start Monitoring` and `Pause Monitoring` controls with a single `ttk.Checkbutton` monitoring switch
- Import pipeline moved to a separate worker process to keep the UI responsive while parsing large files
- `Debug Console` tab is now hidden by default and only shown after the unlock gesture (session-only, non-persistent)


## [1.2.0] - 2026-02-02

### Added
- **Target Stats Panel** - New "Damage Taken" column showing total damage each target has received
  - Displays the sum of all damage dealt to each target from all attackers
  - Column is sortable like all other columns in the panel

### Changed
- **UI Performance Optimizations** - Improved tab switching and panel refresh responsiveness
  - **Dirty Flag Refresh**: `poll_log_file()` now only calls `refresh_targets()` when data has actually changed, using a version counter in DataStore. Eliminates redundant refreshes every 500ms when idle
  - **Optimized Sorting**: `SortedTreeview.apply_current_sort()` now checks if data is already in correct order before sorting, skipping O(n log n) sort operations when unnecessary
  - **Batch Visual Updates**: Target Stats and Immunity panels now suppress Treeview repaints during bulk insert operations using `tree.configure(show="")` pattern, reducing layout recalculations
  - **DataStore Version Tracking**: Added `version` property to DataStore that increments on every data modification, enabling efficient change detection


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



