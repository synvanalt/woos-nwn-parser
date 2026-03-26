"""Benchmark ParserSession wrapper overhead on ordinary non-death lines."""

from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.line_parser import LineParser
from app.parser import ParserSession


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)


@dataclass(frozen=True)
class VariantResult:
    fixture: str
    variant: str
    line_count: int
    event_count: int
    median_s: float
    ns_per_line: float


class _FixedTimestampProvider:
    def __init__(self, timestamp: datetime) -> None:
        self._timestamp = timestamp

    def get(self) -> datetime:
        return self._timestamp


class _NoOpLineParser:
    WHISPER_MARKER = LineParser.WHISPER_MARKER
    KILLED_MARKER = LineParser.KILLED_MARKER

    def __init__(self) -> None:
        self.player_name: Optional[str] = None
        self.parse_immunity = True

    @property
    def death_identify_token(self) -> str:
        return LineParser.DEATH_IDENTIFY_TOKEN

    @staticmethod
    def normalize_name(value: str) -> str:
        return value

    def extract_timestamp_parts(self, line: str) -> Optional[tuple[int, int, int, int, int]]:
        return LineParser().extract_timestamp_parts(line)

    def build_timestamp_from_parts(
        self,
        parts: tuple[int, int, int, int, int],
        *,
        year: int,
    ) -> Optional[datetime]:
        return LineParser.build_timestamp_from_parts(parts, year=year)

    def is_whisper_line(self, raw_line: str) -> bool:
        return False

    def is_killed_line(self, raw_line: str) -> bool:
        return False

    def match_chat_whisper(self, raw_line: str) -> None:
        return None

    def match_killed_line(self, raw_line: str) -> None:
        return None

    def parse_line(
        self,
        raw_line: str,
        *,
        line_number: int,
        get_timestamp: Callable[[], datetime],
    ) -> None:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark ParserSession wrapper overhead.")
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--fixtures",
        nargs="*",
        default=[str(path) for path in DEFAULT_FIXTURES],
    )
    return parser.parse_args()


def load_non_death_lines(path: Path) -> list[str]:
    fallback = ParserSession.DEFAULT_DEATH_FALLBACK_LINE
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if (
                LineParser.WHISPER_MARKER in line
                or LineParser.KILLED_MARKER in line
                or fallback in line
            ):
                continue
            if line.strip():
                lines.append(line)
    return lines


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def count_events(events: list[object]) -> int:
    return sum(1 for event in events if event is not None)


def benchmark_variant(
    *,
    lines: list[str],
    runner: Callable[[list[str]], list[object]],
    iterations: int,
    warmups: int,
) -> tuple[float, int]:
    for _ in range(warmups):
        runner(lines)

    timings: list[float] = []
    event_count = 0
    for _ in range(iterations):
        started = perf_counter()
        events = runner(lines)
        elapsed = perf_counter() - started
        timings.append(elapsed)
        event_count = count_events(events)

    return median(timings), event_count


def run_session_full(lines: list[str]) -> list[object]:
    parser = ParserSession(parse_immunity=True)
    return [parser.parse_line(line) for line in lines]


def run_session_wrapper_only(lines: list[str]) -> list[object]:
    parser = ParserSession(line_parser=_NoOpLineParser(), parse_immunity=True)
    return [parser.parse_line(line) for line in lines]


def run_line_parser_with_closure(lines: list[str]) -> list[object]:
    parser = LineParser(parse_immunity=True)
    fixed_timestamp = datetime(2026, 3, 9, 12, 0, 0)
    results: list[object] = []
    for index, line in enumerate(lines, start=1):
        raw_line = line.rstrip("\r\n")

        def get_timestamp() -> datetime:
            return fixed_timestamp

        results.append(parser.parse_line(raw_line, line_number=index, get_timestamp=get_timestamp))
    return results


def run_line_parser_with_bound_method(lines: list[str]) -> list[object]:
    parser = LineParser(parse_immunity=True)
    provider = _FixedTimestampProvider(datetime(2026, 3, 9, 12, 0, 0))
    results: list[object] = []
    for index, line in enumerate(lines, start=1):
        results.append(
            parser.parse_line(
                line.rstrip("\r\n"),
                line_number=index,
                get_timestamp=provider.get,
            )
        )
    return results


def run_timestamp_resolution(lines: list[str]) -> list[object]:
    parser = ParserSession(parse_immunity=True)
    return [parser.extract_timestamp_from_line(line.rstrip("\r\n")) for line in lines]


def main() -> None:
    args = parse_args()
    variants: list[tuple[str, Callable[[list[str]], list[object]]]] = [
        ("session_full", run_session_full),
        ("session_wrapper_only", run_session_wrapper_only),
        ("line_parser_closure_callback", run_line_parser_with_closure),
        ("line_parser_bound_method", run_line_parser_with_bound_method),
        ("timestamp_resolution_only", run_timestamp_resolution),
    ]

    rows: list[VariantResult] = []
    comparable_event_counts: dict[str, int] = {}
    for fixture_name in args.fixtures:
        fixture = Path(fixture_name)
        lines = load_non_death_lines(fixture)
        for variant_name, runner in variants:
            median_s, event_count = benchmark_variant(
                lines=lines,
                runner=runner,
                iterations=args.iterations,
                warmups=args.warmups,
            )
            if variant_name in {"session_full", "line_parser_closure_callback", "line_parser_bound_method"}:
                previous = comparable_event_counts.get(fixture.name)
                if previous is None:
                    comparable_event_counts[fixture.name] = event_count
                elif previous != event_count:
                    raise RuntimeError(
                        f"Comparable parser event counts differ for {fixture.name}: "
                        f"expected {previous}, got {event_count} in {variant_name}"
                    )
            rows.append(
                VariantResult(
                    fixture=fixture.name,
                    variant=variant_name,
                    line_count=len(lines),
                    event_count=event_count,
                    median_s=median_s,
                    ns_per_line=(median_s / len(lines)) * 1_000_000_000 if lines else 0.0,
                )
            )

    headers = ("fixture", "variant", "line_count", "event_count", "median_s", "ns_per_line")
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted = {
            "fixture": row.fixture,
            "variant": row.variant,
            "line_count": str(row.line_count),
            "event_count": str(row.event_count),
            "median_s": f"{row.median_s:.4f}",
            "ns_per_line": f"{row.ns_per_line:.0f}",
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Parser session overhead benchmark")
    print(f"Iterations: {args.iterations} measured, {args.warmups} warmup")
    print("Input set: ordinary non-death lines only")
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted_rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()
