"""Benchmark import ops memory for materialized-vs-streaming strategies."""

from __future__ import annotations

import argparse
import statistics
import sys
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.utils import _iter_file_ops_chunks


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)

OPS_KEYS = (
    "dps_updates",
    "damage_events",
    "immunity_records",
    "attack_events",
    "save_events",
    "epic_dodge_targets",
    "death_snippets",
)


def _peak_mib(run_once) -> float:
    tracemalloc.start()
    run_once()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / (1024 * 1024)


def _consume_streaming(path: Path, parse_immunity: bool, chunk_size: int) -> int:
    consumed = 0
    for chunk in _iter_file_ops_chunks(
        str(path),
        parse_immunity=parse_immunity,
        chunk_size=chunk_size,
    ):
        for key in OPS_KEYS:
            consumed += len(chunk.get(key, []))
    return consumed


def _consume_materialized(path: Path, parse_immunity: bool, chunk_size: int) -> int:
    all_ops = {key: [] for key in OPS_KEYS}
    for chunk in _iter_file_ops_chunks(
        str(path),
        parse_immunity=parse_immunity,
        chunk_size=10**9,
    ):
        for key in OPS_KEYS:
            all_ops[key].extend(chunk.get(key, []))

    consumed = 0
    max_len = max((len(values) for values in all_ops.values()), default=0)
    for i in range(0, max_len, chunk_size):
        for key in OPS_KEYS:
            consumed += len(all_ops[key][i:i + chunk_size])
    return consumed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark import ops peak memory for materialized and streaming strategies."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Measured runs per fixture/mode/strategy.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2000,
        help="Chunk size used by streaming and materialized replay.",
    )
    parser.add_argument(
        "--fixtures",
        nargs="*",
        default=[str(path) for path in DEFAULT_FIXTURES],
        help="Fixture files to benchmark.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixtures = [Path(path) for path in args.fixtures]

    headers = (
        "file",
        "mode",
        "stream_peak_mib",
        "materialized_peak_mib",
        "delta_mib",
        "delta_pct",
    )
    rows: list[dict[str, str]] = []

    for fixture in fixtures:
        for parse_immunity in (False, True):
            stream_values = [
                _peak_mib(lambda: _consume_streaming(fixture, parse_immunity, args.chunk_size))
                for _ in range(args.iterations)
            ]
            materialized_values = [
                _peak_mib(lambda: _consume_materialized(fixture, parse_immunity, args.chunk_size))
                for _ in range(args.iterations)
            ]

            stream_peak = float(statistics.median(stream_values))
            materialized_peak = float(statistics.median(materialized_values))
            delta = materialized_peak - stream_peak
            delta_pct = (delta / materialized_peak * 100.0) if materialized_peak else 0.0

            rows.append(
                {
                    "file": fixture.name,
                    "mode": "parse_immunity=on" if parse_immunity else "parse_immunity=off",
                    "stream_peak_mib": f"{stream_peak:.3f}",
                    "materialized_peak_mib": f"{materialized_peak:.3f}",
                    "delta_mib": f"{delta:.3f}",
                    "delta_pct": f"{delta_pct:.1f}%",
                }
            )

    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            widths[header] = max(widths[header], len(row[header]))

    print("Benchmark import ops memory (tracemalloc peak)")
    print(f"Iterations: {args.iterations}, chunk_size: {args.chunk_size}")
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()
