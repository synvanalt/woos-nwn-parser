# Immunity Matching

## Purpose
This document is the internal source of truth for how damage immunity lines are parsed, matched, stored, and displayed in the app.

Read this before changing immunity parsing, the shared matcher, import/live parity, or the `Target Immunities` panel.

## Relevant Code Paths
- `app/parser.py`: parses raw NWN log lines into `damage_dealt` and `immunity` events and assigns monotonic `line_number`.
- `app/services/immunity_matcher.py`: shared matching logic used by both live monitoring and historic import.
- `app/services/queue_processor.py`: live monitoring path; feeds parsed events into the matcher and applies resulting mutations.
- `app/utils.py`: historic import path; feeds parsed events into the same matcher during file parsing and worker import.
- `app/storage.py`: stores matched immunity samples in `immunity_data` and exposes panel-facing summaries.

## Game And Log Behavior
NWN does not guarantee that damage immunity lines appear after the matching damage line.

Observed real-log patterns include:
- damage line followed by one or more immunity lines for the same target
- immunity line before the matching damage line
- same-second bursts with multiple damage lines against the same target
- unrelated lines interleaved between damage and immunity
- incoming damage against the player, where the player is the immunity target
- zero-damage components such as `0 Electrical`, which still matter because the game can emit immunity lines for them

This is why immunity matching cannot rely only on "last damage for target" or on timestamp alone.

## Parsing Model
The parser does not directly compute immunity samples. It emits events:
- `damage_dealt`
- `immunity`

For immunity work, the important parser outputs are:
- normalized `target`
- parsed `damage_type`
- parsed `timestamp`
- monotonic `line_number`

`line_number` is important because same-second timestamps are common in dense combat logs.

## Shared Matching Model
Both live monitoring and historic import use the same matcher in `app/services/immunity_matcher.py`.

The matcher works on per-component observations keyed by:
- `(target, damage_type)`

That means a hit like:
- `59 (46 Physical 0 Cold 8 Fire 2 Sonic 3 Pure)`

is treated as separate damage observations for `Physical`, `Cold`, `Fire`, `Sonic`, and `Pure`.

Immunity lines are also stored as per-type observations.

Only matched pairs become `ImmunityMutation`s.

## Matching Rules
Current matching is conservative and deterministic.

An immunity observation and damage observation are eligible only when:
- `target` matches exactly
- `damage_type` matches exactly
- absolute timestamp delta is `<= 1.0` second
- absolute line-number gap is `<= 12`

Candidate ranking is:
1. same-second candidate before cross-second candidate
2. smaller line-number gap
3. smaller timestamp delta
4. earlier candidate line number

Current behavior:
- if there is one unique best candidate, the pair is matched
- if no candidate is eligible, the observation stays pending
- pending observations are cleaned up once they age out of the configured stale window

This matcher is shared on purpose so live monitoring and file import produce the same immunity behavior.

## Live And Import Flow
### Live monitoring
- `app/parser.py` emits parsed events.
- `app/services/queue_processor.py` inserts damage rows, sends damage and immunity observations to the matcher, and applies matched `ImmunityMutation`s to the store.

### Historic import
- `app/utils.py` parses the file line by line.
- It feeds the same parsed events into the same shared matcher.
- Matched `ImmunityMutation`s are emitted into the import mutation stream.

If you change matcher behavior, both paths must stay in sync.

## Storage Semantics
Matched immunity samples are stored separately from raw damage events in `DataStore.immunity_data`.

Important semantics:
- `sample_count` counts matched immunity samples only
- `max_damage` and `max_immunity` are kept coupled from the same matched sample
- the store updates the "max" record when a later matched sample has higher `damage_dealt`
- if `damage_dealt` ties, the store keeps the higher `immunity_points` value for that same damage tier
- zero-damage matched samples are valid; if all matched samples for a target/type have `damage_dealt == 0`, the stored pair can still be `(0, absorbed)`
- matched temporary full-absorb samples remain stored and counted even if later positive same-type damage proves the target is not stably `100%` immune

This coupling matters because the immunity percentage display assumes the absorbed value and damage value came from the same hit.

## Panel Semantics
The `Target Immunities` panel renders query-prepared display rows built from store summaries, not ad hoc log scans.

Important consequences:
- displayed immunity percentages are derived from matched samples only
- unmatched immunity observations do not contribute to `sample_count`
- `max_event_damage` can still exist even when there is no matched immunity sample for that type
- when immunity parsing is enabled and a matched sample exists with `max_damage == 0`, the panel shows `Max Damage = 0`, the stored absorbed value, and `Immunity % = 100%`
- exception: if `sample_count > 0`, `max_immunity_damage == 0`, and `max_event_damage > 0`, the store summary suppresses that temporary full-immunity evidence for display and the panel shows `Max Damage = max_event_damage`, `Absorbed = -`, and `Immunity % = -`
- when exact reverse-immunity inference fails for a positive-damage matched sample, the app shows the closest simulated immunity percentage instead of `-`
- closest-match ties resolve to the lower immunity percentage
- displayed immunity percentages can still be overstated if the target also has damage resistance or damage reduction

The temporary-full-immunity suppression flag is derived from the store summary, while the final UI-facing string formatting now lives in the immunity query layer rather than the Tk widget. Live monitoring and historic import still store the same matched immunity samples; only the panel-facing projection changes.

## Known Limitations
- Dense same-second combat still relies on heuristic nearest-match behavior; the log format does not provide a perfect hit identifier.
- The matcher is deterministic, but it is not guaranteed to reconstruct absolute game truth in every crowded burst.
- The shared matcher rewrite improved correctness and live/import parity, but it introduced measurable performance regressions on `parse_immunity=on`.

## Benchmarks And Validation
When changing this area, use:

```powershell
python scripts/benchmark_baseline.py
```

Use the default real fixtures:
- `tests/fixtures/real_flurry_conceal_epicdodge.txt`
- `tests/fixtures/real_deadwyrm_offhand_crit_mix.txt`
- `tests/fixtures/real_tod_risen_save_dense.txt`

At minimum, run targeted tests covering:
- damage before immunity
- immunity before damage
- same-second nearest matching
- live queue processing
- historic import and worker parsing

Current regression tests touching this area include:
- `tests/unit/test_queue_processor_unit.py`
- `tests/unit/test_queue_processor.py`
- `tests/unit/test_queue_processor_resilience.py`
- `tests/unit/test_utils_worker_pipeline.py`
- `tests/integration/test_parser_storage_integration.py`

Report benchmark medians before and after any matcher-path performance change.

