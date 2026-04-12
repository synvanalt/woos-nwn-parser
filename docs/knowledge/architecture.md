# Architecture

This document is the architecture reference for the current `app/` structure. Planning docs under `docs/` may describe how the repo got here, but this file is the source of truth when they differ.

## Project Structure

```text
woos-nwn-parser/
|-- app/                           # Main application code
|   |-- __init__.py
|   |-- __main__.py                # Entry point
|   |-- constants.py               # Shared constants (damage type palette)
|   |-- models.py                  # Data models
|   |-- parser.py                  # Stable parser facade/re-exports
|   |-- line_parser.py             # Pure line parsing logic
|   |-- parser_session.py          # Stateful parser/session correlation
|   |-- storage.py                 # Mutable session store and indexed reads
|   |-- monitor.py                 # File monitoring and rotation
|   |-- settings.py                # User settings persistence
|   |-- utils.py                   # Utility functions
|   |-- assets/                    # Application resources
|   |-- services/
|   |   |-- __init__.py
|   |   |-- event_ingestion.py     # Shared parsed-event normalization
|   |   |-- immunity_matcher.py    # Shared damage/immunity correlation
|   |   |-- queue_processor.py     # Live queue draining and batching
|   |   `-- queries/               # Read-side query services for UI projections
|   |       `-- models.py          # Typed read-side DTOs for query results
|   `-- ui/
|       |-- __init__.py
|       |-- main_window.py         # Main application window
|       |-- runtime_config.py      # Typed runtime policy defaults
|       |-- formatters.py          # Data formatting utilities
|       |-- tree_refresh.py        # Shared treeview refresh/diff helpers
|       |-- controllers/           # Workflow/policy coordinators
|       |-- presenters/            # Pure render-preparation helpers for widgets
|       |-- window_style.py        # Window styling helpers
|       `-- widgets/               # UI components
|           |-- __init__.py
|           |-- dps_panel.py
|           |-- target_stats_panel.py
|           |-- immunity_panel.py
|           |-- death_snippet_panel.py
|           |-- debug_console_panel.py
|           `-- sorted_treeview.py
|-- tests/                         # Test suite
|   |-- unit/                      # Unit tests
|   |-- integration/               # Integration tests
|   |-- e2e/                       # End-to-end tests
|   `-- fixtures/                  # Test data
|-- docs/                          # Documentation
|-- WoosNwnParser-onedir.spec      # PyInstaller build spec - one directory
|-- WoosNwnParser-onefile.spec     # PyInstaller build spec - one file
|-- requirements.txt
|-- requirements-dev.txt
|-- CHANGELOG.md
`-- README.md
```

## Runtime Flow

The main live-data path is:

`monitor -> parser -> queue processor / event ingestion -> DataStore -> query services -> UI panels`

- `LogDirectoryMonitor` tails the active NWN log and feeds raw lines into the parser pipeline
- `ParserSession` owns line numbering, year inference, and death-correlation state while routing each raw line through `LineParser`
- `LineParser` converts individual lines into typed parsed events for damage, attacks, saves, immunities, and other pure per-line observations
- `QueueProcessor` drains parsed events in bounded batches and routes them through `EventIngestionEngine`
- `EventIngestionEngine` turns parsed events into normalized store mutations and side events
- `DataStore` applies mutations and updates the indexed in-memory session state
- Query services build panel-facing read models from those indices
- Tk widgets render the query-service results and preserve incremental refresh behavior

Historic import uses the same parser and ingestion logic, then applies the resulting mutations into the same `DataStore`.

## Ownership Boundaries

- `DataStore` owns mutable indexed combat state, versioning, locking, and mutation application
- `DataStore` also owns store-facing immutable read snapshots for query consumption, including atomic projection snapshots when query timing state must stay consistent with indexed summaries
- Query services own read-side row construction, memoization, and typed immutable DTO return semantics for the UI
- `app/ui/runtime_config.py` owns typed runtime-tuning policy for queue draining, monitor pacing, import streaming, and the hidden debug unlock gesture
- UI controllers coordinate workflows such as monitoring, import, queue draining, coalesced refreshes, persisted session settings, and hidden debug unlock handling
- `app/ui/tree_refresh.py` owns shared top-level tree diffing, selection preservation, stale-item fallback, and sort-preservation behavior for the heavy table widgets
- UI presenters/formatters own pure display-data preparation that widgets can consume without Tk dependencies
- Panels should consume query services, not build projections directly from low-level store state
- Parser and matcher semantics should stay aligned across live monitoring and historic import

## Key Components

**ParserSession** (`parser.py`, `parser_session.py`)
- Owns the stateful parser API used by production code
- Tracks line numbering, recent-line history, death snippet correlation, fallback death detection, and year rollover inference
- Exposes the session-level parser controls used by UI and import flows, including immunity parsing and death-snippet settings
- The supported constructor surface is the current keyword-only session configuration (line_parser, parse_immunity, max_recent_log_lines, anchor_year)

**LineParser** (`parser.py`, `line_parser.py`)
- Owns pure regex and fast-path parsing for individual log lines
- Emits typed parsed events for damage, attacks, saves, immunities, and epic dodge
- Provides narrow helper methods used by `ParserSession` for whisper/killed-line recognition without exposing raw parser internals as the session contract
- The supported timestamp helper surface is `extract_timestamp_parts(...)` plus `build_timestamp_from_parts(...)`
- `app/parser.py` is the parser import boundary for callers outside the parser internals

**DataStore** (`storage.py`)
- Thread-safe in-memory session storage
- Owns mutable indexed combat state and batched mutation application
- Tracks attacks, damage totals, immunities, and target-stat aggregation (AC/AB/Saves)
- Owns write-side mutations plus immutable store-facing read snapshots consumed by query services
- Keeps lock ownership inside the store when building timing-sensitive read projections so query services do not assemble mixed-version DPS state from multiple lock acquisitions

**LogDirectoryMonitor** (`monitor.py`)
- Watches NWN logs directory for changes
- Handles log rotation (`nwclientLog1.txt` -> `nwclientLog2.txt`, etc.)
- Detects file truncation from game restarts
- Uses bounded per-poll parsing to avoid long blocking reads when backlog grows

**Settings Persistence** (`settings.py`)
- Loads and saves user preferences used across app restarts
- Persists selected log directory, Death Snippets fallback log line, and the `Parse Immunities` toggle
- Settings are saved at `%LOCALAPPDATA%\\WoosNwnParser\\settings.json`

**QueueProcessor** (`services/queue_processor.py`)
- Drains the live parser queue in bounded batches
- Consumes typed parsed events through the shared ingestion engine
- Aggregates deduplicated UI refresh targets and side events into the drain result
- Manages periodic cleanup of stale immunity queue entries

**ImmunityMatcher** (`services/immunity_matcher.py`)
- Shares immunity matching logic between live monitoring and file import paths
- Conservatively pairs immunity lines with nearby damage observations by target, damage type, timestamp, and line number
- Keeps unmatched damage/immunity observations in bounded queues and prunes stale entries

**EventIngestionEngine** (`services/event_ingestion.py`)
- Converts typed parsed damage, attack, save, immunity, and death events into normalized store mutations and side events
- Owns the transient immunity-matching state used by both live monitoring and historic import
- Keeps live queue processing and import payload generation aligned through one shared normalization path

**Query Services** (`services/queries/`)
- `DpsQueryService` builds DPS rows, hit-rate display data, and damage-type breakdowns from store indices
- `TargetSummaryQueryService` builds `Target Stats` rows from indexed target state
- `ImmunityQueryService` builds prepared `Target Immunities` display rows from store-owned damage/immunity snapshots
- `services/queries/models.py` defines the typed immutable DTOs returned by those services
- Keep read-side projection caching out of `DataStore`, while consuming store-owned immutable snapshots and returning typed read-model DTOs for UI consumers
- UI-facing display semantics such as immunity-percent formatting, absorbed-value suppression, and parse-toggle-specific row presentation belong here rather than in Tk widgets
- Query services expose an explicit `supports_store_version_fast_path` capability that heavy widgets consult before using version-based no-op refresh short-circuits; widgets should not infer this by inspecting method identity or monkeypatch state

**WoosNwnParserApp** (`ui/main_window.py`)
- Acts as the UI composition root: constructs parser, storage, query dependencies, widgets, runtime policy, and controllers
- Owns only app-level Tk callbacks such as target selection fanout, settings-triggered refreshes, clear/reset orchestration, and shutdown ordering
- Delegates monitoring, import, queue-drain, settings persistence, and hidden debug unlock behavior to focused controllers

**Tree Refresh Helpers** (`ui/tree_refresh.py`)
- Own shared top-level tree rebuild and incremental-update mechanics for `DPSPanel`, `TargetStatsPanel`, and `ImmunityPanel`
- Preserve selected rows across full rebuilds, recover safely from stale cached item ids, and distinguish authoritative natural order from user-selected sorts
- Keep nested DPS child-row handling in the widget layer so the shared helper stays focused on flat top-level rows

**DeathSnippetPresenter** (`ui/presenters/death_snippet_presenter.py`)
- Owns pure death-snippet render preparation outside Tk widgets
- Sanitizes display lines, infers opponent names, shapes no-wrap display lines, and prepares name/damage highlight spans
- Returns prepared render instructions that the widget can map onto Tk text tags

**UI Controllers** (`ui/controllers/`)
- `MonitorController` owns live monitor start/pause, background file polling, active-file status updates, and monitoring switch styling
- `ImportController` owns the `Load & Parse Logs` workflow, modal progress UI, worker process, strict worker-payload normalization, and incremental payload application
- `QueueDrainController` owns bounded queue draining, pressure-based scheduling, and monitor backpressure policy
- `RefreshCoordinator` owns coalesced heavy-panel refreshes after queue drains
- `SessionSettingsController` owns loading, building, debouncing, and persisting session settings
- `DebugUnlockController` owns the hidden `Debug Console` notebook-click gesture policy and reveal callback triggering

**Runtime Policy** (`ui/runtime_config.py`)
- `AppRuntimeConfig` groups typed runtime policy for queue drain budgets, monitor scheduling, import pacing, and hidden debug unlock behavior
- `DEFAULT_APP_RUNTIME_CONFIG` is the single source of truth for app-shell tuning values that were previously embedded as `WoosNwnParserApp` constants

**DeathSnippetPanel** (`ui/widgets/death_snippet_panel.py`)
- Displays death-context snippets with a `Killed by:` dropdown (newest first)
- Supports character auto-identification from whisper token and runtime fallback log-line configuration
- Owns Tk layout, selection state, line-wrap behavior, and text-tag application
- Consumes prepared render instructions from the death-snippet presenter for character-name and damage-type highlighting

## Related Knowledge Docs

- `docs/knowledge/immunity-matching.md`: immunity matching rules, heuristics, and live/import parity details
