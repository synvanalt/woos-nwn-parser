"""Benchmark multiprocessing import IPC path (worker + queue + consumer)."""

from __future__ import annotations

import argparse
import importlib
import queue as std_queue
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)


@dataclass(frozen=True)
class FixtureInfo:
    path: Path
    line_count: int


@dataclass(frozen=True)
class RunResult:
    seconds: float
    events_seen: int
    chunks_seen: int
    files_completed: int
    ops_items_seen: int
    done_seen: bool
    aborted_seen: bool


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for _ in handle)


def _median(values: Iterable[float]) -> float:
    return float(statistics.median(list(values)))


def _mean(values: Iterable[float]) -> float:
    return float(statistics.mean(list(values)))


def _format_rate(units: float, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return units / seconds


def _clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def _benchmark_one_run(
    fixture_path: Path,
    parse_immunity: bool,
    consumer_delay_ms: float,
) -> RunResult:
    # Import app modules lazily so caller can choose repo root.
    utils = importlib.import_module("app.utils")
    parser_mod = importlib.import_module("app.parser")
    import_worker_process = getattr(utils, "import_worker_process")
    queue_maxsize = int(getattr(utils, "IMPORT_RESULT_QUEUE_MAXSIZE", 0))
    default_fallback = getattr(parser_mod.LogParser, "DEFAULT_DEATH_FALLBACK_LINE")

    mp = importlib.import_module("multiprocessing")
    ctx = mp.get_context("spawn")
    abort_event = ctx.Event()
    result_queue = ctx.Queue(maxsize=queue_maxsize)
    proc = ctx.Process(
        target=import_worker_process,
        args=(
            [str(fixture_path)],
            bool(parse_immunity),
            abort_event,
            result_queue,
            "",
            default_fallback,
        ),
        daemon=True,
    )

    events_seen = 0
    chunks_seen = 0
    files_completed = 0
    ops_items_seen = 0
    done_seen = False
    aborted_seen = False
    delay_seconds = max(0.0, consumer_delay_ms / 1000.0)

    started = time.perf_counter()
    proc.start()
    try:
        while True:
            try:
                event = result_queue.get(timeout=0.05)
            except std_queue.Empty:
                if not proc.is_alive() and done_seen:
                    break
                continue

            events_seen += 1
            event_type = event.get("event")
            if event_type == "ops_chunk":
                chunks_seen += 1
                ops = event.get("ops", {})
                if isinstance(ops, dict):
                    for value in ops.values():
                        if isinstance(value, list):
                            ops_items_seen += len(value)
            elif event_type == "file_completed":
                files_completed += 1
            elif event_type == "done":
                done_seen = True
            elif event_type == "aborted":
                aborted_seen = True
                break

            if delay_seconds > 0:
                time.sleep(delay_seconds)

            if done_seen and not proc.is_alive():
                # Drain any last messages quickly.
                while True:
                    try:
                        extra = result_queue.get_nowait()
                    except std_queue.Empty:
                        break
                    events_seen += 1
                    if extra.get("event") == "ops_chunk":
                        chunks_seen += 1
                        ops = extra.get("ops", {})
                        if isinstance(ops, dict):
                            for value in ops.values():
                                if isinstance(value, list):
                                    ops_items_seen += len(value)
                    elif extra.get("event") == "file_completed":
                        files_completed += 1
                    elif extra.get("event") == "aborted":
                        aborted_seen = True
                break
    finally:
        proc.join(timeout=2.0)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)

    elapsed = time.perf_counter() - started
    return RunResult(
        seconds=elapsed,
        events_seen=events_seen,
        chunks_seen=chunks_seen,
        files_completed=files_completed,
        ops_items_seen=ops_items_seen,
        done_seen=done_seen,
        aborted_seen=aborted_seen,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark multiprocessing import IPC worker and queue behavior."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repo root to benchmark (for before/after comparisons).",
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
        "--consumer-delay-ms",
        type=float,
        default=0.0,
        help="Artificial per-event consumer delay in milliseconds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        raise RuntimeError(f"repo root not found: {repo_root}")

    fixture_infos = []
    for fixture in args.fixtures:
        path = (repo_root / fixture).resolve()
        if not path.exists():
            raise RuntimeError(f"fixture not found: {path}")
        fixture_infos.append(FixtureInfo(path=path, line_count=_count_lines(path)))

    _clear_app_modules()
    sys.path.insert(0, str(repo_root))

    rows: list[dict[str, object]] = []
    for fixture in fixture_infos:
        for parse_immunity in (False, True):
            for _ in range(args.warmups):
                _benchmark_one_run(
                    fixture_path=fixture.path,
                    parse_immunity=parse_immunity,
                    consumer_delay_ms=args.consumer_delay_ms,
                )
            results = [
                _benchmark_one_run(
                    fixture_path=fixture.path,
                    parse_immunity=parse_immunity,
                    consumer_delay_ms=args.consumer_delay_ms,
                )
                for _ in range(args.iterations)
            ]
            times = [result.seconds for result in results]
            latest = results[-1]
            rows.append({
                "file": fixture.path.name,
                "mode": "parse_immunity=on" if parse_immunity else "parse_immunity=off",
                "min_s": min(times),
                "median_s": _median(times),
                "mean_s": _mean(times),
                "max_s": max(times),
                "spread_pct": ((_median(times) and (max(times) - min(times)) / _median(times) * 100.0) or 0.0),
                "lines_per_s": _format_rate(fixture.line_count, _median(times)),
                "events_seen": latest.events_seen,
                "chunks_seen": latest.chunks_seen,
                "files_completed": latest.files_completed,
                "ops_items_seen": latest.ops_items_seen,
                "done_seen": latest.done_seen,
                "aborted_seen": latest.aborted_seen,
            })

    headers = (
        "file",
        "mode",
        "min_s",
        "median_s",
        "max_s",
        "spread_pct",
        "lines_per_s",
        "events_seen",
        "chunks_seen",
        "files_completed",
        "ops_items_seen",
        "done_seen",
        "aborted_seen",
    )
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted = {
            "file": str(row["file"]),
            "mode": str(row["mode"]),
            "min_s": f"{row['min_s']:.4f}",
            "median_s": f"{row['median_s']:.4f}",
            "max_s": f"{row['max_s']:.4f}",
            "spread_pct": f"{row['spread_pct']:.1f}%",
            "lines_per_s": f"{row['lines_per_s']:.0f}",
            "events_seen": str(row["events_seen"]),
            "chunks_seen": str(row["chunks_seen"]),
            "files_completed": str(row["files_completed"]),
            "ops_items_seen": str(row["ops_items_seen"]),
            "done_seen": str(row["done_seen"]),
            "aborted_seen": str(row["aborted_seen"]),
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Benchmark import IPC")
    print(f"Repo: {repo_root}")
    print(f"Consumer delay: {args.consumer_delay_ms:.3f} ms/event")
    print(f"Iterations: {args.iterations} measured, {args.warmups} warmup")
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted_rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()
