"""Benchmark parser-only and full-import performance on fixture logs."""

from __future__ import annotations

import argparse
import importlib
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)


@dataclass(frozen=True)
class FixtureInfo:
    """Static details about a benchmark input file."""

    path: Path
    size_bytes: int
    line_count: int


@dataclass(frozen=True)
class RunResult:
    """One timed benchmark run."""

    seconds: float
    parsed_events: int
    store_events: int
    store_attacks: int
    dps_entries: int
    immunity_targets: int


@dataclass(frozen=True)
class RuntimeBindings:
    """Lazy-loaded app symbols for one repo root."""

    parser_cls: type
    data_store_cls: type
    parse_and_import_file: Callable[[str, Any, Any], dict[str, Any]]


def clear_app_modules() -> None:
    """Unload app modules so alternate repo roots can be imported cleanly."""
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def load_runtime(repo_root: Path) -> RuntimeBindings:
    """Import benchmark bindings from the requested repo root."""
    clear_app_modules()
    repo_root_str = str(repo_root)
    if repo_root_str in sys.path:
        sys.path.remove(repo_root_str)
    sys.path.insert(0, repo_root_str)

    parser_mod = importlib.import_module("app.parser")
    storage_mod = importlib.import_module("app.storage")
    utils_mod = importlib.import_module("app.utils")
    return RuntimeBindings(
        parser_cls=getattr(parser_mod, "LogParser"),
        data_store_cls=getattr(storage_mod, "DataStore"),
        parse_and_import_file=getattr(utils_mod, "parse_and_import_file"),
    )


def count_lines(path: Path) -> int:
    """Count file lines without loading the whole file into memory."""
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def build_fixture_info(path: Path) -> FixtureInfo:
    """Collect immutable file metadata used in benchmark reporting."""
    return FixtureInfo(
        path=path,
        size_bytes=path.stat().st_size,
        line_count=count_lines(path),
    )


def benchmark_parser_only(runtime: RuntimeBindings, path: Path, parse_immunity: bool) -> RunResult:
    """Time raw line parsing without store mutations."""
    parser = runtime.parser_cls(parse_immunity=parse_immunity)
    parsed_events = 0

    started = perf_counter()
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if parser.parse_line(line):
                parsed_events += 1
    elapsed = perf_counter() - started

    return RunResult(
        seconds=elapsed,
        parsed_events=parsed_events,
        store_events=0,
        store_attacks=0,
        dps_entries=0,
        immunity_targets=0,
    )


def benchmark_full_import(runtime: RuntimeBindings, path: Path, parse_immunity: bool) -> RunResult:
    """Time the current import pipeline, including store mutation costs."""
    parser = runtime.parser_cls(parse_immunity=parse_immunity)
    store = runtime.data_store_cls()

    started = perf_counter()
    result = runtime.parse_and_import_file(str(path), parser, store)
    elapsed = perf_counter() - started

    if not result.get("success"):
        raise RuntimeError(f"Import failed for {path}: {result.get('error')}")

    return RunResult(
        seconds=elapsed,
        parsed_events=len(store.events) + len(store.attacks),
        store_events=len(store.events),
        store_attacks=len(store.attacks),
        dps_entries=len(store.dps_data),
        immunity_targets=len(store.immunity_data),
    )


def median(values: Iterable[float]) -> float:
    """Return a stable median as float."""
    return float(statistics.median(list(values)))


def mean(values: Iterable[float]) -> float:
    """Return a stable mean as float."""
    return float(statistics.mean(list(values)))


def format_throughput(units: float, seconds: float) -> float:
    """Convert a duration into units/sec."""
    if seconds <= 0:
        return 0.0
    return units / seconds


def run_case(
    runtime: RuntimeBindings,
    fixture: FixtureInfo,
    label: str,
    runner: Callable[[RuntimeBindings, Path, bool], RunResult],
    parse_immunity: bool,
    iterations: int,
    warmups: int,
) -> dict[str, object]:
    """Run one benchmark scenario and summarize repeated timings."""
    for _ in range(warmups):
        runner(runtime, fixture.path, parse_immunity)

    results = [runner(runtime, fixture.path, parse_immunity) for _ in range(iterations)]
    times = [result.seconds for result in results]
    median_seconds = median(times)

    latest = results[-1]
    mb_size = fixture.size_bytes / (1024 * 1024)

    return {
        "file": fixture.path.name,
        "mode": "parse_immunity=on" if parse_immunity else "parse_immunity=off",
        "layer": label,
        "lines": fixture.line_count,
        "size_mb": mb_size,
        "min_s": min(times),
        "median_s": median_seconds,
        "mean_s": mean(times),
        "max_s": max(times),
        "spread_pct": ((max(times) - min(times)) / median_seconds * 100.0) if median_seconds else 0.0,
        "lines_per_s": format_throughput(fixture.line_count, median_seconds),
        "mb_per_s": format_throughput(mb_size, median_seconds),
        "parsed_events": latest.parsed_events,
        "store_events": latest.store_events,
        "store_attacks": latest.store_attacks,
        "dps_entries": latest.dps_entries,
        "immunity_targets": latest.immunity_targets,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Benchmark parser-only and full-import performance on fixture logs."
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
    """Execute the benchmark suite and print a compact report."""
    args = parse_args()
    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        raise RuntimeError(f"repo root not found: {repo_root}")
    runtime = load_runtime(repo_root)
    fixture_infos = [build_fixture_info((repo_root / Path(path)).resolve()) for path in args.fixtures]

    rows: list[dict[str, object]] = []
    for fixture in fixture_infos:
        iterations = args.iterations
        if (
            args.large_fixture_iterations > 0
            and fixture.line_count >= args.large_fixture_line_threshold
        ):
            iterations = args.large_fixture_iterations
        for parse_immunity in (False, True):
            rows.append(
                run_case(
                    runtime,
                    fixture,
                    "parser_only",
                    benchmark_parser_only,
                    parse_immunity,
                    iterations,
                    args.warmups,
                )
            )
            rows.append(
                run_case(
                    runtime,
                    fixture,
                    "full_import",
                    benchmark_full_import,
                    parse_immunity,
                    iterations,
                    args.warmups,
                )
            )

    headers = (
        "file",
        "mode",
        "layer",
        "min_s",
        "median_s",
        "max_s",
        "spread_pct",
        "lines_per_s",
        "mb_per_s",
        "parsed_events",
        "store_events",
        "store_attacks",
        "dps_entries",
        "immunity_targets",
    )
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted = {
            "file": str(row["file"]),
            "mode": str(row["mode"]),
            "layer": str(row["layer"]),
            "min_s": f"{row['min_s']:.4f}",
            "median_s": f"{row['median_s']:.4f}",
            "max_s": f"{row['max_s']:.4f}",
            "spread_pct": f"{row['spread_pct']:.1f}%",
            "lines_per_s": f"{row['lines_per_s']:.0f}",
            "mb_per_s": f"{row['mb_per_s']:.2f}",
            "parsed_events": str(row["parsed_events"]),
            "store_events": str(row["store_events"]),
            "store_attacks": str(row["store_attacks"]),
            "dps_entries": str(row["dps_entries"]),
            "immunity_targets": str(row["immunity_targets"]),
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Benchmark baseline")
    print(f"Repo: {repo_root}")
    print(
        "Iterations: "
        f"{args.iterations} measured, {args.warmups} warmup"
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
