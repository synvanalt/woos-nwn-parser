"""Benchmark repeated store/service read-refresh cost after fixture import."""

from __future__ import annotations

import argparse
import importlib
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Optional


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)


@dataclass(frozen=True)
class FixtureInfo:
    """Static metadata for one fixture file."""

    path: Path
    line_count: int


@dataclass(frozen=True)
class RuntimeBindings:
    """Lazy-loaded app symbols for one repo root."""

    data_store_cls: type
    dps_query_service_cls: type
    target_summary_query_service_cls: type
    immunity_query_service_cls: type
    parser_cls: type
    parse_and_import_file: Callable[[str, Any, Any], dict[str, Any]]
    damage_mutation_cls: type
    attack_mutation_cls: type
    immunity_mutation_cls: type


@dataclass(frozen=True)
class RefreshCounts:
    """Observed output sizes from one refresh bundle execution."""

    rows_seen: int
    targets_seen: int
    characters_seen: int


@dataclass(frozen=True)
class RunResult:
    """One measured benchmark run."""

    seconds: float
    counts: RefreshCounts


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _median(values: Iterable[float]) -> float:
    return float(statistics.median(list(values)))


def _format_rate(units: float, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return units / seconds


def _clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def _load_runtime(repo_root: Path) -> RuntimeBindings:
    _clear_app_modules()
    repo_root_str = str(repo_root)
    if repo_root_str in sys.path:
        sys.path.remove(repo_root_str)
    sys.path.insert(0, repo_root_str)

    storage_mod = importlib.import_module("app.storage")
    queries_mod = importlib.import_module("app.services.queries")
    parser_mod = importlib.import_module("app.parser")
    utils_mod = importlib.import_module("app.utils")
    models_mod = importlib.import_module("app.models")

    return RuntimeBindings(
        data_store_cls=getattr(storage_mod, "DataStore"),
        dps_query_service_cls=getattr(queries_mod, "DpsQueryService"),
        target_summary_query_service_cls=getattr(queries_mod, "TargetSummaryQueryService"),
        immunity_query_service_cls=getattr(queries_mod, "ImmunityQueryService"),
        parser_cls=getattr(parser_mod, "ParserSession"),
        parse_and_import_file=getattr(utils_mod, "parse_and_import_file"),
        damage_mutation_cls=getattr(models_mod, "DamageMutation"),
        attack_mutation_cls=getattr(models_mod, "AttackMutation"),
        immunity_mutation_cls=getattr(models_mod, "ImmunityMutation"),
    )


def _build_store(
    runtime: RuntimeBindings,
) -> Any:
    return runtime.data_store_cls()


def _build_dps_query_service(runtime: RuntimeBindings, store: Any, *, disable_query_cache: bool) -> Any:
    if not disable_query_cache:
        return runtime.dps_query_service_cls(store)

    class BenchmarkNoCacheDpsQueryService(runtime.dps_query_service_cls):
        """Disable query-service cache reuse for benchmark comparison."""

        def _reset_caches_if_needed(self) -> None:
            super()._reset_caches_if_needed()
            self._dps_data_cache.clear()
            self._dps_breakdowns_cache.clear()
            self._hit_rate_cache.clear()

    return BenchmarkNoCacheDpsQueryService(store)


def _build_target_summary_query_service(
    runtime: RuntimeBindings,
    store: Any,
    *,
    disable_query_cache: bool,
) -> Any:
    if not disable_query_cache:
        return runtime.target_summary_query_service_cls(store)

    class BenchmarkNoCacheTargetSummaryQueryService(runtime.target_summary_query_service_cls):
        """Disable target-summary cache reuse for benchmark comparison."""

        def _reset_caches_if_needed(self) -> None:
            super()._reset_caches_if_needed()
            self._summary_cache = None

    return BenchmarkNoCacheTargetSummaryQueryService(store)


def _build_immunity_query_service(
    runtime: RuntimeBindings,
    store: Any,
    *,
    disable_query_cache: bool,
) -> Any:
    if not disable_query_cache:
        return runtime.immunity_query_service_cls(store)

    class BenchmarkNoCacheImmunityQueryService(runtime.immunity_query_service_cls):
        """Disable immunity display-row cache reuse for benchmark comparison."""

        def _reset_caches_if_needed(self) -> None:
            super()._reset_caches_if_needed()
            self._display_cache.clear()

    return BenchmarkNoCacheImmunityQueryService(store)


def _import_fixture(
    runtime: RuntimeBindings,
    fixture_path: Path,
    *,
    parse_immunity: bool,
) -> tuple[Any, Any]:
    parser = runtime.parser_cls(parse_immunity=parse_immunity)
    store = _build_store(runtime)
    result = runtime.parse_and_import_file(str(fixture_path), parser, store)
    if not result.get("success"):
        raise RuntimeError(f"Import failed for {fixture_path}: {result.get('error')}")
    return parser, store


def _select_primary_target(target_summary_query_service: Any) -> Optional[str]:
    summary = target_summary_query_service.get_all_targets_summary()
    if not summary:
        return None
    best_row = max(summary, key=lambda row: int(row.damage_taken))
    return str(best_row.target)


def _select_mutation_character(store: Any, service: Any, target: Optional[str]) -> str:
    if target:
        dps_rows = service.get_dps_display_data(target_filter=target)
        if dps_rows:
            return str(dps_rows[0].character)
    dps_rows = service.get_dps_display_data(target_filter="All")
    if dps_rows:
        return str(dps_rows[0].character)
    if store.dps_data:
        return str(next(iter(store.dps_data)))
    return "BenchmarkAttacker"


def _select_mutation_damage_type(
    store: Any,
    immunity_query_service: Any,
    target: Optional[str],
    *,
    parse_immunity: bool,
) -> str:
    if target:
        rows = immunity_query_service.get_target_immunity_display_rows(
            target,
            parse_immunity=parse_immunity,
        )
        if rows:
            return str(rows[0].damage_type)
    damage_types = store.get_all_damage_types()
    if damage_types:
        return str(damage_types[0])
    return "Physical"


def _count_bundle_result(payload: Any) -> RefreshCounts:
    if isinstance(payload, list):
        characters_seen = 0
        if payload:
            if hasattr(payload[0], "character"):
                characters_seen = len(payload)
            elif hasattr(payload[0], "target"):
                return RefreshCounts(
                    rows_seen=len(payload),
                    targets_seen=len(payload),
                    characters_seen=0,
                )
        return RefreshCounts(
            rows_seen=len(payload),
            targets_seen=0,
            characters_seen=characters_seen,
        )

    if isinstance(payload, dict):
        rows_seen = 0
        for rows in payload.values():
            if isinstance(rows, list):
                rows_seen += len(rows)
        return RefreshCounts(
            rows_seen=rows_seen,
            targets_seen=0,
            characters_seen=len(payload),
        )

    return RefreshCounts(rows_seen=0, targets_seen=0, characters_seen=0)


def _run_dps_all_bundle(service: Any) -> RefreshCounts:
    dps_rows = service.get_dps_display_data(target_filter="All")
    characters = [str(row.character) for row in dps_rows]
    breakdowns = service.get_damage_type_breakdowns(characters, target_filter="All")
    dps_counts = _count_bundle_result(dps_rows)
    breakdown_counts = _count_bundle_result(breakdowns)
    return RefreshCounts(
        rows_seen=dps_counts.rows_seen + breakdown_counts.rows_seen,
        targets_seen=0,
        characters_seen=dps_counts.characters_seen,
    )


def _run_dps_target_bundle(service: Any, target: Optional[str]) -> Optional[RefreshCounts]:
    if not target:
        return None
    dps_rows = service.get_dps_display_data(target_filter=target)
    characters = [str(row.character) for row in dps_rows]
    breakdowns = service.get_damage_type_breakdowns(characters, target_filter=target)
    dps_counts = _count_bundle_result(dps_rows)
    breakdown_counts = _count_bundle_result(breakdowns)
    return RefreshCounts(
        rows_seen=dps_counts.rows_seen + breakdown_counts.rows_seen,
        targets_seen=1,
        characters_seen=dps_counts.characters_seen,
    )


def _run_target_summary_bundle(target_summary_query_service: Any) -> RefreshCounts:
    return _count_bundle_result(target_summary_query_service.get_all_targets_summary())


def _run_immunity_target_bundle(
    immunity_query_service: Any,
    target: Optional[str],
    *,
    parse_immunity: bool,
) -> Optional[RefreshCounts]:
    if not target:
        return None
    counts = _count_bundle_result(
        immunity_query_service.get_target_immunity_display_rows(
            target,
            parse_immunity=parse_immunity,
        )
    )
    return RefreshCounts(
        rows_seen=counts.rows_seen,
        targets_seen=1,
        characters_seen=0,
    )


def _build_bundle_callbacks(
    dps_query_service: Any,
    target_summary_query_service: Any,
    immunity_query_service: Any,
    target: Optional[str],
    *,
    parse_immunity: bool,
) -> list[tuple[str, Callable[[], Optional[RefreshCounts]]]]:
    callbacks: list[tuple[str, Callable[[], Optional[RefreshCounts]]]] = [
        ("dps_all_bundle", lambda: _run_dps_all_bundle(dps_query_service)),
        ("target_summary_bundle", lambda: _run_target_summary_bundle(target_summary_query_service)),
    ]
    if target:
        callbacks.append(("dps_target_bundle", lambda: _run_dps_target_bundle(dps_query_service, target)))
        callbacks.append(
            (
                "immunity_target_bundle",
                lambda: _run_immunity_target_bundle(
                    immunity_query_service,
                    target,
                    parse_immunity=parse_immunity,
                ),
            )
        )
    return callbacks


def _apply_live_refresh_mutation(
    runtime: RuntimeBindings,
    store: Any,
    *,
    parse_immunity: bool,
    target: Optional[str],
    character: str,
    damage_type: str,
    cycle_index: int,
) -> None:
    chosen_target = target or _select_primary_target(store) or "BenchmarkTarget"
    base_timestamp = store.last_damage_timestamp or store.get_earliest_timestamp() or datetime.now()
    timestamp = base_timestamp + timedelta(seconds=cycle_index + 1)
    total_damage = 7 + (cycle_index % 5)
    attack_total = 20 + (cycle_index % 7)

    mutations = [
        runtime.damage_mutation_cls(
            target=chosen_target,
            damage_type=damage_type,
            total_damage=total_damage,
            attacker=character,
            timestamp=timestamp,
        ),
        runtime.damage_mutation_cls(
            target=chosen_target,
            total_damage=total_damage,
            attacker=character,
            timestamp=timestamp,
            count_for_dps=True,
            damage_types={damage_type: total_damage},
        ),
        runtime.attack_mutation_cls(
            attacker=character,
            target=chosen_target,
            outcome="hit",
            bonus=12,
            total=attack_total,
        ),
    ]
    if parse_immunity:
        mutations.append(
            runtime.immunity_mutation_cls(
                target=chosen_target,
                damage_type=damage_type,
                immunity_points=1 + (cycle_index % 3),
                damage_dealt=total_damage,
            )
        )

    store.apply_mutations(mutations)


def _time_bundle(
    callback: Callable[[], Optional[RefreshCounts]],
    *,
    cycles_per_iteration: int,
    before_each_cycle: Optional[Callable[[int], None]] = None,
) -> RunResult:
    last_counts = RefreshCounts(rows_seen=0, targets_seen=0, characters_seen=0)
    started = perf_counter()
    for cycle_index in range(cycles_per_iteration):
        if before_each_cycle is not None:
            before_each_cycle(cycle_index)
        counts = callback()
        if counts is not None:
            last_counts = counts
    elapsed = perf_counter() - started
    return RunResult(seconds=elapsed, counts=last_counts)


def _run_case(
    runtime: RuntimeBindings,
    fixture: FixtureInfo,
    *,
    parse_immunity: bool,
    disable_query_cache: bool,
    workload: str,
    bundle_name: str,
    cycles_per_iteration: int,
    iterations: int,
    warmups: int,
    before_each_cycle_factory: Optional[Callable[[Any, Any, Any, Any, Optional[str]], Callable[[int], None]]] = None,
) -> dict[str, object]:
    for _ in range(warmups):
        _, warm_store = _import_fixture(
            runtime,
            fixture.path,
            parse_immunity=parse_immunity,
        )
        warm_dps_query_service = _build_dps_query_service(
            runtime,
            warm_store,
            disable_query_cache=disable_query_cache,
        )
        warm_target_summary_query_service = _build_target_summary_query_service(
            runtime,
            warm_store,
            disable_query_cache=disable_query_cache,
        )
        warm_immunity_query_service = _build_immunity_query_service(
            runtime,
            warm_store,
            disable_query_cache=disable_query_cache,
        )
        warm_target = _select_primary_target(warm_target_summary_query_service)
        warm_callback = next(
            callback
            for name, callback in _build_bundle_callbacks(
                warm_dps_query_service,
                warm_target_summary_query_service,
                warm_immunity_query_service,
                warm_target,
                parse_immunity=parse_immunity,
            )
            if name == bundle_name
        )
        warm_callback()
        before_each_cycle = None
        if before_each_cycle_factory is not None:
            before_each_cycle = before_each_cycle_factory(
                warm_store,
                warm_dps_query_service,
                warm_target_summary_query_service,
                warm_immunity_query_service,
                warm_target,
            )
        _time_bundle(
            warm_callback,
            cycles_per_iteration=cycles_per_iteration,
            before_each_cycle=before_each_cycle,
        )

    results: list[RunResult] = []
    expected_counts: Optional[RefreshCounts] = None
    for _ in range(iterations):
        _, store = _import_fixture(
            runtime,
            fixture.path,
            parse_immunity=parse_immunity,
        )
        dps_query_service = _build_dps_query_service(
            runtime,
            store,
            disable_query_cache=disable_query_cache,
        )
        target_summary_query_service = _build_target_summary_query_service(
            runtime,
            store,
            disable_query_cache=disable_query_cache,
        )
        immunity_query_service = _build_immunity_query_service(
            runtime,
            store,
            disable_query_cache=disable_query_cache,
        )
        target = _select_primary_target(target_summary_query_service)
        callback = next(
            callback
            for name, callback in _build_bundle_callbacks(
                dps_query_service,
                target_summary_query_service,
                immunity_query_service,
                target,
                parse_immunity=parse_immunity,
            )
            if name == bundle_name
        )
        callback()
        before_each_cycle = None
        if before_each_cycle_factory is not None:
            before_each_cycle = before_each_cycle_factory(
                store,
                dps_query_service,
                target_summary_query_service,
                immunity_query_service,
                target,
            )
        result = _time_bundle(
            callback,
            cycles_per_iteration=cycles_per_iteration,
            before_each_cycle=before_each_cycle,
        )
        if expected_counts is None:
            expected_counts = result.counts
        elif expected_counts != result.counts:
            raise RuntimeError(
                "Bundle output sizes changed across repeated runs for "
                f"{fixture.path.name} / {bundle_name} / {workload}"
            )
        results.append(result)

    times = [result.seconds for result in results]
    median_seconds = _median(times)
    latest = results[-1]
    return {
        "file": fixture.path.name,
        "mode": "parse_immunity=on" if parse_immunity else "parse_immunity=off",
        "query_cache": "off" if disable_query_cache else "on",
        "workload": workload,
        "bundle": bundle_name,
        "min_ms": min(times) * 1000.0,
        "median_ms": median_seconds * 1000.0,
        "max_ms": max(times) * 1000.0,
        "spread_pct": ((max(times) - min(times)) / median_seconds * 100.0) if median_seconds else 0.0,
        "refreshes_per_s": _format_rate(cycles_per_iteration, median_seconds),
        "rows_seen": latest.counts.rows_seen,
        "targets_seen": latest.counts.targets_seen,
        "characters_seen": latest.counts.characters_seen,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark repeated store/service read-refresh cost after fixture import."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repo root to benchmark.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Measured runs per scenario after warmup.",
    )
    parser.add_argument(
        "--warmups",
        type=int,
        default=1,
        help="Unmeasured warmup runs per scenario.",
    )
    parser.add_argument(
        "--fixtures",
        nargs="*",
        default=[str(path) for path in DEFAULT_FIXTURES],
        help="Fixture files to benchmark.",
    )
    parser.add_argument(
        "--parse-immunity",
        action="store_true",
        help="Benchmark only with immunity parsing enabled. Default runs both off and on.",
    )
    parser.add_argument(
        "--read-mix",
        choices=("steady_state", "live_refresh", "both"),
        default="both",
        help="Read-refresh workload family to benchmark.",
    )
    parser.add_argument(
        "--cycles-per-iteration",
        type=int,
        default=200,
        help="Read-refresh cycles inside one measured run.",
    )
    parser.add_argument(
        "--large-fixture-line-threshold",
        type=int,
        default=10000,
        help="Line count at or above which large-fixture iterations are used.",
    )
    parser.add_argument(
        "--large-fixture-iterations",
        type=int,
        default=9,
        help="Measured runs for large fixtures; use 0 to disable adaptive scaling.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    runtime = _load_runtime(repo_root)

    fixture_infos = []
    for fixture in args.fixtures:
        path = (repo_root / fixture).resolve()
        if not path.exists():
            raise RuntimeError(f"fixture not found: {path}")
        fixture_infos.append(FixtureInfo(path=path, line_count=_count_lines(path)))

    parse_immunity_modes = (True,) if args.parse_immunity else (False, True)
    rows: list[dict[str, object]] = []
    for fixture in fixture_infos:
        iterations = args.iterations
        if (
            args.large_fixture_iterations > 0
            and fixture.line_count >= args.large_fixture_line_threshold
        ):
            iterations = args.large_fixture_iterations

        for parse_immunity in parse_immunity_modes:
            workloads: list[tuple[str, Optional[Callable[[Any, Any, Optional[str]], Callable[[int], None]]]]] = [
                ("steady_state", None),
                (
                    "live_refresh",
                    lambda store, dps_query_service, _target_summary_query_service, immunity_query_service, target, parse_immunity=parse_immunity: (
                        lambda cycle_index: _apply_live_refresh_mutation(
                            runtime,
                            store,
                            parse_immunity=parse_immunity,
                            target=target,
                            character=_select_mutation_character(store, dps_query_service, target),
                            damage_type=_select_mutation_damage_type(
                                store,
                                immunity_query_service,
                                target,
                                parse_immunity=parse_immunity,
                            ),
                            cycle_index=cycle_index,
                        )
                    ),
                ),
            ]
            if args.read_mix == "steady_state":
                workloads = workloads[:1]
            elif args.read_mix == "live_refresh":
                workloads = workloads[1:]

            _, probe_store = _import_fixture(
                runtime,
                fixture.path,
                parse_immunity=parse_immunity,
            )
            probe_dps_query_service = _build_dps_query_service(
                runtime,
                probe_store,
                disable_query_cache=False,
            )
            probe_target_summary_query_service = _build_target_summary_query_service(
                runtime,
                probe_store,
                disable_query_cache=False,
            )
            probe_immunity_query_service = _build_immunity_query_service(
                runtime,
                probe_store,
                disable_query_cache=False,
            )
            probe_target = _select_primary_target(probe_target_summary_query_service)
            bundle_names = [
                name
                for name, _ in _build_bundle_callbacks(
                    probe_dps_query_service,
                    probe_target_summary_query_service,
                    probe_immunity_query_service,
                    probe_target,
                    parse_immunity=parse_immunity,
                )
            ]

            for workload_name, before_each_cycle_factory in workloads:
                for disable_query_cache in (False, True):
                    for bundle_name in bundle_names:
                        rows.append(
                            _run_case(
                                runtime,
                                fixture,
                                parse_immunity=parse_immunity,
                                disable_query_cache=disable_query_cache,
                                workload=workload_name,
                                bundle_name=bundle_name,
                                cycles_per_iteration=args.cycles_per_iteration,
                                iterations=iterations,
                                warmups=args.warmups,
                                before_each_cycle_factory=before_each_cycle_factory,
                            )
                        )

    paired_medians = {
        (
                row["file"],
                row["mode"],
                row["workload"],
                row["bundle"],
                row["query_cache"],
            ): float(row["median_ms"])
        for row in rows
    }

    for row in rows:
        off_median = paired_medians.get(
            (
                row["file"],
                row["mode"],
                row["workload"],
                row["bundle"],
                "off",
            )
        )
        on_median = paired_medians.get(
            (
                row["file"],
                row["mode"],
                row["workload"],
                row["bundle"],
                "on",
            )
        )
        if off_median is None or on_median is None or on_median <= 0:
            row["speedup_vs_off"] = "-"
        elif row["query_cache"] == "on":
            row["speedup_vs_off"] = f"{off_median / on_median:.2f}x"
        else:
            row["speedup_vs_off"] = "1.00x"

    paired_counts = {}
    for row in rows:
        key = (row["file"], row["mode"], row["workload"], row["bundle"])
        counts = (
            int(row["rows_seen"]),
            int(row["targets_seen"]),
            int(row["characters_seen"]),
        )
        existing = paired_counts.get(key)
        if existing is None:
            paired_counts[key] = counts
        elif existing != counts:
            raise RuntimeError(
                "cache on/off changed benchmark output sizes for "
                f"{row['file']} / {row['mode']} / {row['workload']} / {row['bundle']}"
            )

    headers = (
        "file",
        "mode",
        "query_cache",
        "workload",
        "bundle",
        "min_ms",
        "median_ms",
        "max_ms",
        "spread_pct",
        "refreshes_per_s",
        "rows_seen",
        "targets_seen",
        "characters_seen",
        "speedup_vs_off",
    )
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted = {
            "file": str(row["file"]),
            "mode": str(row["mode"]),
            "query_cache": str(row["query_cache"]),
            "workload": str(row["workload"]),
            "bundle": str(row["bundle"]),
            "min_ms": f"{row['min_ms']:.3f}",
            "median_ms": f"{row['median_ms']:.3f}",
            "max_ms": f"{row['max_ms']:.3f}",
            "spread_pct": f"{row['spread_pct']:.1f}%",
            "refreshes_per_s": f"{row['refreshes_per_s']:.1f}",
            "rows_seen": str(row["rows_seen"]),
            "targets_seen": str(row["targets_seen"]),
            "characters_seen": str(row["characters_seen"]),
            "speedup_vs_off": str(row["speedup_vs_off"]),
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Read refresh benchmark")
    print(
        "Iterations: "
        f"{args.iterations} measured, {args.warmups} warmup, "
        f"{args.cycles_per_iteration} cycles per measured run"
        f" ({args.large_fixture_iterations} measured for fixtures with "
        f"{args.large_fixture_line_threshold}+ lines)"
    )
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted_rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()

