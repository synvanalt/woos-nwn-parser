"""Benchmark parser component costs on real fixture subsets."""

from __future__ import annotations

import argparse
import importlib
import json
import statistics
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)
HEAVY_FIXTURES = {
    "real_deadwyrm_offhand_crit_mix.txt",
    "real_tod_risen_save_dense.txt",
}
SUBSETS = (
    "ordinary_non_death",
    "damage",
    "immunity",
    "attack_basic",
    "attack_threat",
    "save",
    "other",
)
PARSER_VARIANTS = {
    "session_full",
    "line_parser_closure_callback",
    "line_parser_bound_method",
}
MODE_VALUES = ("off", "on")
FIXED_TIMESTAMP = datetime(2026, 3, 9, 12, 0, 0)


@dataclass(frozen=True)
class RuntimeBindings:
    parser_cls: type
    line_parser_cls: type


@dataclass(frozen=True)
class Row:
    fixture: str
    subset: str
    mode: str
    variant: str
    line_count: int
    event_count: int
    median_s: float
    ns_per_line: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark parser component costs on real fixtures.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--fixtures",
        nargs="*",
        default=[str(path) for path in DEFAULT_FIXTURES],
    )
    parser.add_argument("--json-out", type=Path, default=None)
    return parser.parse_args()


def clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def load_runtime(repo_root: Path) -> RuntimeBindings:
    clear_app_modules()
    repo_root_str = str(repo_root)
    if repo_root_str in sys.path:
        sys.path.remove(repo_root_str)
    sys.path.insert(0, repo_root_str)

    parser_mod = importlib.import_module("app.parser")
    line_parser_mod = importlib.import_module("app.line_parser")
    return RuntimeBindings(
        parser_cls=getattr(parser_mod, "ParserSession"),
        line_parser_cls=getattr(line_parser_mod, "LineParser"),
    )


def classify_line(line: str) -> str:
    if " damages " in line:
        return "damage"
    if "Damage Immunity absorbs" in line:
        return "immunity"
    if " attacks " in line:
        if "attacker miss chance:" in line:
            return "attack_miss_chance"
        if "target concealed:" in line:
            return "attack_conceal"
        if "Threat Roll:" in line:
            return "attack_threat"
        return "attack_basic"
    if " Save" in line:
        return "save"
    if "Epic Dodge" in line:
        return "epic_dodge"
    if "Your God refuses to hear your prayers!" in line:
        return "death_prayer"
    if " killed " in line:
        return "killed"
    return "other"


def load_fixture_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return [line.rstrip("\r\n") for line in handle if line.strip()]


def build_subsets(lines: list[str]) -> dict[str, list[str]]:
    grouped = {subset: [] for subset in SUBSETS}
    for line in lines:
        category = classify_line(line)
        if category not in {"death_prayer", "killed"}:
            grouped["ordinary_non_death"].append(line)
        if category in grouped:
            grouped[category].append(line)
    return grouped


def extract_damage_breakdowns(lines: list[str], parser: LineParser) -> list[str]:
    pattern = parser.patterns["damage_dealt"]
    payloads: list[str] = []
    for line in lines:
        match = pattern.search(line)
        if match:
            payloads.append(match.group(4))
    return payloads


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def count_events(events: list[object]) -> int:
    return sum(1 for event in events if event is not None)


def bench_runner(
    *,
    runner: Callable[[], list[object]],
    iterations: int,
    warmups: int,
) -> tuple[float, int]:
    for _ in range(warmups):
        runner()

    timings: list[float] = []
    event_count = 0
    for _ in range(iterations):
        started = perf_counter()
        events = runner()
        timings.append(perf_counter() - started)
        event_count = count_events(events)

    return median(timings), event_count


class _FixedTimestampProvider:
    def get(self) -> datetime:
        return FIXED_TIMESTAMP


class _NoOpLineParser:
    def __init__(self, line_parser_cls: type) -> None:
        self.player_name: Optional[str] = None
        self.parse_immunity = True
        self._line_parser_cls = line_parser_cls
        self.WHISPER_MARKER = line_parser_cls.WHISPER_MARKER
        self.KILLED_MARKER = line_parser_cls.KILLED_MARKER
        self._timestamp_parser = line_parser_cls()

    @property
    def death_identify_token(self) -> str:
        return self._line_parser_cls.DEATH_IDENTIFY_TOKEN

    @staticmethod
    def normalize_name(value: str) -> str:
        return value

    def extract_timestamp_parts(self, line: str) -> Optional[tuple[int, int, int, int, int]]:
        return self._timestamp_parser.extract_timestamp_parts(line)

    def build_timestamp_from_parts(
        self,
        parts: tuple[int, int, int, int, int],
        *,
        year: int,
    ) -> Optional[datetime]:
        return self._line_parser_cls.build_timestamp_from_parts(parts, year=year)

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


def run_session_full(runtime: RuntimeBindings, lines: list[str], parse_immunity: bool) -> list[object]:
    parser = runtime.parser_cls(parse_immunity=parse_immunity)
    return [parser.parse_line(line) for line in lines]


def run_session_wrapper_only(runtime: RuntimeBindings, lines: list[str], parse_immunity: bool) -> list[object]:
    parser = runtime.parser_cls(
        line_parser=_NoOpLineParser(runtime.line_parser_cls),
        parse_immunity=parse_immunity,
    )
    return [parser.parse_line(line) for line in lines]


def run_line_parser_with_closure(runtime: RuntimeBindings, lines: list[str], parse_immunity: bool) -> list[object]:
    parser = runtime.line_parser_cls(parse_immunity=parse_immunity)
    results: list[object] = []
    for index, line in enumerate(lines, start=1):
        raw_line = line

        def get_timestamp() -> datetime:
            return FIXED_TIMESTAMP

        results.append(parser.parse_line(raw_line, line_number=index, get_timestamp=get_timestamp))
    return results


def run_line_parser_with_bound_method(runtime: RuntimeBindings, lines: list[str], parse_immunity: bool) -> list[object]:
    parser = runtime.line_parser_cls(parse_immunity=parse_immunity)
    provider = _FixedTimestampProvider()
    return [
        parser.parse_line(line, line_number=index, get_timestamp=provider.get)
        for index, line in enumerate(lines, start=1)
    ]


def run_recent_log_append_only(lines: list[str]) -> list[object]:
    recent = deque(maxlen=max(1, len(lines)))
    for line in lines:
        recent.append(line)
    return [None] * len(lines)


def run_timestamp_resolution_only(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.parser_cls(parse_immunity=True)
    return [parser.extract_timestamp_from_line(line) for line in lines]


def run_strip_chat_prefix_only(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    return [parser._strip_chat_prefix(line) for line in lines]


def run_damage_breakdown_only(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = extract_damage_breakdowns(lines, parser)
    return [parser.parse_damage_breakdown(payload) for payload in payloads]


def ns_per_line(seconds: float, line_count: int) -> float:
    if line_count <= 0:
        return 0.0
    return (seconds / line_count) * 1_000_000_000


def format_ratio(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def safe_share(part: float, whole: float) -> Optional[float]:
    if whole <= 0:
        return None
    return (part / whole) * 100.0


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        raise RuntimeError(f"repo root not found: {repo_root}")
    global _GLOBAL_RUNTIME
    _GLOBAL_RUNTIME = load_runtime(repo_root)
    rows: list[Row] = []
    comparable_counts: dict[tuple[str, str, str], int] = {}

    for fixture_name in args.fixtures:
        fixture = (repo_root / Path(fixture_name)).resolve()
        fixture_lines = load_fixture_lines(fixture)
        subsets = build_subsets(fixture_lines)

        for subset_name in SUBSETS:
            subset_lines = subsets[subset_name]
            if not subset_lines:
                continue

            for parse_immunity in MODE_VALUES:
                parse_immunity_value = parse_immunity == "on"
                mode_label = f"parse_immunity={parse_immunity}"

                parser_variants = [
                    ("session_full", lambda lines=subset_lines, mode=parse_immunity_value: run_session_full(_GLOBAL_RUNTIME, lines, mode)),
                    ("session_wrapper_only", lambda lines=subset_lines, mode=parse_immunity_value: run_session_wrapper_only(_GLOBAL_RUNTIME, lines, mode)),
                    ("line_parser_closure_callback", lambda lines=subset_lines, mode=parse_immunity_value: run_line_parser_with_closure(_GLOBAL_RUNTIME, lines, mode)),
                    ("line_parser_bound_method", lambda lines=subset_lines, mode=parse_immunity_value: run_line_parser_with_bound_method(_GLOBAL_RUNTIME, lines, mode)),
                ]
                for variant_name, runner in parser_variants:
                    median_s, event_count = bench_runner(
                        runner=runner,
                        iterations=args.iterations,
                        warmups=args.warmups,
                    )
                    key = (fixture.name, subset_name, mode_label)
                    if variant_name in PARSER_VARIANTS:
                        previous = comparable_counts.get(key)
                        if previous is None:
                            comparable_counts[key] = event_count
                        elif previous != event_count:
                            raise RuntimeError(
                                f"Comparable parser event counts differ for {fixture.name} {subset_name} {mode_label}: "
                                f"expected {previous}, got {event_count} in {variant_name}"
                            )
                    rows.append(
                        Row(
                            fixture=fixture.name,
                            subset=subset_name,
                            mode=mode_label,
                            variant=variant_name,
                            line_count=len(subset_lines),
                            event_count=event_count,
                            median_s=median_s,
                            ns_per_line=ns_per_line(median_s, len(subset_lines)),
                        )
                    )

            non_parser_variants = [
                ("recent_log_append_only", lambda lines=subset_lines: run_recent_log_append_only(lines)),
                ("timestamp_resolution_only", lambda lines=subset_lines: run_timestamp_resolution_only(lines)),
                ("strip_chat_prefix_only", lambda lines=subset_lines: run_strip_chat_prefix_only(lines)),
            ]
            if subset_name == "damage":
                non_parser_variants.append(
                    ("damage_breakdown_only", lambda lines=subset_lines: run_damage_breakdown_only(lines))
                )

            for variant_name, runner in non_parser_variants:
                median_s, event_count = bench_runner(
                    runner=runner,
                    iterations=args.iterations,
                    warmups=args.warmups,
                )
                effective_line_count = len(subset_lines)
                if variant_name == "damage_breakdown_only":
                    effective_line_count = len(
                        extract_damage_breakdowns(
                            subset_lines,
                            _GLOBAL_RUNTIME.line_parser_cls(),
                        )
                    )
                rows.append(
                    Row(
                        fixture=fixture.name,
                        subset=subset_name,
                        mode="n/a",
                        variant=variant_name,
                        line_count=effective_line_count,
                        event_count=event_count,
                        median_s=median_s,
                        ns_per_line=ns_per_line(median_s, effective_line_count),
                    )
                )

    headers = ("fixture", "subset", "mode", "variant", "line_count", "event_count", "median_s", "ns_per_line")
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted = {
            "fixture": row.fixture,
            "subset": row.subset,
            "mode": row.mode,
            "variant": row.variant,
            "line_count": str(row.line_count),
            "event_count": str(row.event_count),
            "median_s": f"{row.median_s:.4f}",
            "ns_per_line": f"{row.ns_per_line:.0f}",
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Parser component cost benchmark")
    print(f"Repo: {repo_root}")
    print(f"Iterations: {args.iterations} measured, {args.warmups} warmup")
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted_rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))

    print()
    print("Heavy fixture gap summary")
    summary_headers = (
        "fixture",
        "session_gap_vs_line_parser_ns",
        "timestamp_share_of_gap_pct",
        "wrapper_share_of_gap_pct",
        "strip_prefix_share_of_gap_pct",
        "append_share_of_gap_pct",
    )
    summary_widths = {header: len(header) for header in summary_headers}
    summary_rows: list[dict[str, str]] = []
    row_map = {(row.fixture, row.subset, row.mode, row.variant): row for row in rows}
    for fixture_name in sorted(HEAVY_FIXTURES):
        session_row = row_map.get((fixture_name, "ordinary_non_death", "parse_immunity=on", "session_full"))
        closure_row = row_map.get((fixture_name, "ordinary_non_death", "parse_immunity=on", "line_parser_closure_callback"))
        bound_row = row_map.get((fixture_name, "ordinary_non_death", "parse_immunity=on", "line_parser_bound_method"))
        timestamp_row = row_map.get((fixture_name, "ordinary_non_death", "n/a", "timestamp_resolution_only"))
        wrapper_row = row_map.get((fixture_name, "ordinary_non_death", "parse_immunity=on", "session_wrapper_only"))
        strip_row = row_map.get((fixture_name, "ordinary_non_death", "n/a", "strip_chat_prefix_only"))
        append_row = row_map.get((fixture_name, "ordinary_non_death", "n/a", "recent_log_append_only"))
        if not all((session_row, closure_row, bound_row, timestamp_row, wrapper_row, strip_row, append_row)):
            continue
        best_line_parser_ns = min(closure_row.ns_per_line, bound_row.ns_per_line)
        gap_ns = session_row.ns_per_line - best_line_parser_ns
        summary = {
            "fixture": fixture_name,
            "session_gap_vs_line_parser_ns": format_ratio(gap_ns),
            "timestamp_share_of_gap_pct": format_ratio(safe_share(timestamp_row.ns_per_line, gap_ns)),
            "wrapper_share_of_gap_pct": format_ratio(safe_share(wrapper_row.ns_per_line, gap_ns)),
            "strip_prefix_share_of_gap_pct": format_ratio(safe_share(strip_row.ns_per_line, gap_ns)),
            "append_share_of_gap_pct": format_ratio(safe_share(append_row.ns_per_line, gap_ns)),
        }
        summary_rows.append(summary)
        for header, value in summary.items():
            summary_widths[header] = max(summary_widths[header], len(value))

    print(" ".join(header.ljust(summary_widths[header]) for header in summary_headers))
    print(" ".join("-" * summary_widths[header] for header in summary_headers))
    for row in summary_rows:
        print(" ".join(row[header].ljust(summary_widths[header]) for header in summary_headers))

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "repo_root": str(repo_root),
                    "iterations": args.iterations,
                    "warmups": args.warmups,
                    "rows": [row.__dict__ for row in rows],
                    "heavy_fixture_gap_summary": summary_rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
