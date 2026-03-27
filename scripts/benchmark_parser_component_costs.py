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
    damage_event_cls: type


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


@dataclass(frozen=True)
class DamagePayload:
    attacker: str
    target: str
    total_damage: int
    breakdown: str


@dataclass(frozen=True)
class DamageShapeStats:
    single_type_count: int
    multi_type_count: int
    zero_component_count: int
    multiword_type_count: int


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
        damage_event_cls=getattr(importlib.import_module("app.parsed_events"), "DamageDealtEvent"),
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


def extract_damage_breakdowns(lines: list[str], parser: Any) -> list[str]:
    pattern = parser.patterns["damage_dealt"]
    payloads: list[str] = []
    for line in lines:
        match = pattern.search(line)
        if match:
            payloads.append(match.group(4))
    return payloads


def extract_damage_payloads(lines: list[str], parser: Any) -> list[DamagePayload]:
    pattern = parser.patterns["damage_dealt"]
    payloads: list[DamagePayload] = []
    for line in lines:
        match = pattern.search(line)
        if not match:
            continue
        payloads.append(
            DamagePayload(
                attacker=match.group(1).strip(),
                target=match.group(2).strip(),
                total_damage=int(match.group(3)),
                breakdown=match.group(4),
            )
        )
    return payloads


def classify_damage_breakdown_shapes(payloads: list[DamagePayload]) -> DamageShapeStats:
    single_type_count = 0
    multi_type_count = 0
    zero_component_count = 0
    multiword_type_count = 0
    for payload in payloads:
        tokens = payload.breakdown.split()
        component_count = 0
        index = 0
        saw_zero = False
        saw_multiword = False
        while index < len(tokens):
            if not tokens[index].isdigit():
                index += 1
                continue
            amount = int(tokens[index])
            index += 1
            name_count = 0
            while index < len(tokens) and not tokens[index].isdigit():
                name_count += 1
                index += 1
            if name_count > 0:
                component_count += 1
                saw_zero = saw_zero or amount == 0
                saw_multiword = saw_multiword or name_count > 1

        if component_count == 1:
            single_type_count += 1
        elif component_count > 1:
            multi_type_count += 1
        if saw_zero:
            zero_component_count += 1
        if saw_multiword:
            multiword_type_count += 1

    return DamageShapeStats(
        single_type_count=single_type_count,
        multi_type_count=multi_type_count,
        zero_component_count=zero_component_count,
        multiword_type_count=multiword_type_count,
    )


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


def run_damage_regex_extract_only(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    pattern = parser.patterns["damage_dealt"]
    return [pattern.search(line) for line in lines]


def run_damage_regex_groups_only(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    pattern = parser.patterns["damage_dealt"]
    results: list[object] = []
    for line in lines:
        match = pattern.search(line)
        if match is None:
            results.append(None)
            continue
        results.append(
            (
                match.group(1).strip(),
                match.group(2).strip(),
                int(match.group(3)),
                match.group(4),
            )
        )
    return results


def run_damage_event_materialize_empty_breakdown(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = extract_damage_payloads(lines, parser)
    fixed_timestamp = FIXED_TIMESTAMP
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    return [
        event_cls(
            attacker=payload.attacker,
            target=payload.target,
            total_damage=payload.total_damage,
            damage_types={},
            timestamp=fixed_timestamp,
            line_number=index,
        )
        for index, payload in enumerate(payloads, start=1)
    ]


def _build_damage_type_maps(payloads: list[DamagePayload]) -> list[dict[str, int] | None]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    return [parser.parse_damage_breakdown(payload.breakdown) for payload in payloads]


def _build_damage_event_construction_inputs(
    lines: list[str],
) -> tuple[list[DamagePayload], list[dict[str, int] | None]]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = extract_damage_payloads(lines, parser)
    return payloads, _build_damage_type_maps(payloads)


def run_damage_event_materialize_no_types(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = extract_damage_payloads(lines, parser)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    fixed_timestamp = FIXED_TIMESTAMP
    return [
        event_cls(
            attacker=payload.attacker,
            target=payload.target,
            total_damage=payload.total_damage,
            damage_types=None,
            timestamp=fixed_timestamp,
            line_number=index,
        )
        for index, payload in enumerate(payloads, start=1)
    ]


def run_damage_event_materialize_full(lines: list[str]) -> list[object]:
    payloads, damage_type_maps = _build_damage_event_construction_inputs(lines)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    fixed_timestamp = FIXED_TIMESTAMP
    return [
        event_cls(
            attacker=payload.attacker,
            target=payload.target,
            total_damage=payload.total_damage,
            damage_types=damage_types,
            timestamp=fixed_timestamp,
            line_number=index,
        )
        for index, (payload, damage_types) in enumerate(zip(payloads, damage_type_maps), start=1)
    ]


def run_damage_event_construct_keywords(lines: list[str]) -> list[object]:
    payloads, damage_type_maps = _build_damage_event_construction_inputs(lines)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    fixed_timestamp = FIXED_TIMESTAMP
    return [
        event_cls(
            timestamp=fixed_timestamp,
            line_number=index,
            attacker=payload.attacker,
            target=payload.target,
            total_damage=payload.total_damage,
            damage_types=damage_types,
        )
        for index, (payload, damage_types) in enumerate(zip(payloads, damage_type_maps), start=1)
    ]


def run_damage_event_construct_positional(lines: list[str]) -> list[object]:
    payloads, damage_type_maps = _build_damage_event_construction_inputs(lines)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    fixed_timestamp = FIXED_TIMESTAMP
    return [
        event_cls(
            fixed_timestamp,
            index,
            payload.attacker,
            payload.target,
            payload.total_damage,
            damage_types,
        )
        for index, (payload, damage_types) in enumerate(zip(payloads, damage_type_maps), start=1)
    ]


def run_damage_event_construct_prebound_cls(lines: list[str]) -> list[object]:
    payloads, damage_type_maps = _build_damage_event_construction_inputs(lines)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    fixed_timestamp = FIXED_TIMESTAMP
    return [
        event_cls(fixed_timestamp, index, payload.attacker, payload.target, payload.total_damage, damage_types)
        for index, (payload, damage_types) in enumerate(zip(payloads, damage_type_maps), start=1)
    ]


def run_damage_event_construct_prebound_timestamp(lines: list[str]) -> list[object]:
    payloads, damage_type_maps = _build_damage_event_construction_inputs(lines)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    timestamp = FIXED_TIMESTAMP
    return [
        event_cls(timestamp, index, payload.attacker, payload.target, payload.total_damage, damage_types)
        for index, (payload, damage_types) in enumerate(zip(payloads, damage_type_maps), start=1)
    ]


def run_damage_event_construct_without_line_number(lines: list[str]) -> list[object]:
    payloads, damage_type_maps = _build_damage_event_construction_inputs(lines)
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    timestamp = FIXED_TIMESTAMP
    return [
        event_cls(timestamp, None, payload.attacker, payload.target, payload.total_damage, damage_types)
        for payload, damage_types in zip(payloads, damage_type_maps)
    ]


def run_damage_parse_plus_materialize(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    pattern = parser.patterns["damage_dealt"]
    event_cls = _GLOBAL_RUNTIME.damage_event_cls
    results: list[object] = []
    for index, line in enumerate(lines, start=1):
        match = pattern.search(line)
        if match is None:
            continue
        results.append(
            event_cls(
                attacker=match.group(1).strip(),
                target=match.group(2).strip(),
                total_damage=int(match.group(3)),
                damage_types=parser.parse_damage_breakdown(match.group(4)),
                timestamp=FIXED_TIMESTAMP,
                line_number=index,
            )
        )
    return results


def run_damage_parse_plus_materialize_fixed_timestamp(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    provider = _FixedTimestampProvider()
    results: list[object] = []
    for index, line in enumerate(lines, start=1):
        event = parser.parse_line(line, line_number=index, get_timestamp=provider.get)
        if event is not None:
            results.append(event)
    return results


def run_damage_breakdown_split_only(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = extract_damage_breakdowns(lines, parser)
    return [payload.split() for payload in payloads]


def _filter_damage_payloads(
    lines: list[str],
    *,
    single_type_only: bool = False,
    multi_type_only: bool = False,
    zero_component_only: bool = False,
) -> list[str]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    selected: list[str] = []
    for payload in extract_damage_payloads(lines, parser):
        parsed = parser.parse_damage_breakdown(payload.breakdown)
        component_count = len(parsed)
        if single_type_only and component_count != 1:
            continue
        if multi_type_only and component_count <= 1:
            continue
        if zero_component_only and not any(value == 0 for value in parsed.values()):
            continue
        selected.append(payload.breakdown)
    return selected


def run_damage_breakdown_parse_single_type(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = _filter_damage_payloads(lines, single_type_only=True)
    return [parser.parse_damage_breakdown(payload) for payload in payloads]


def run_damage_breakdown_parse_multi_type(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = _filter_damage_payloads(lines, multi_type_only=True)
    return [parser.parse_damage_breakdown(payload) for payload in payloads]


def run_damage_breakdown_parse_zero_heavy(lines: list[str]) -> list[object]:
    parser = _GLOBAL_RUNTIME.line_parser_cls(parse_immunity=True)
    payloads = _filter_damage_payloads(lines, zero_component_only=True)
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


def pct_of(count: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return (count / total) * 100.0


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        raise RuntimeError(f"repo root not found: {repo_root}")
    global _GLOBAL_RUNTIME
    _GLOBAL_RUNTIME = load_runtime(repo_root)
    rows: list[Row] = []
    comparable_counts: dict[tuple[str, str, str], int] = {}
    damage_shape_summary: list[dict[str, object]] = []

    for fixture_name in args.fixtures:
        fixture = (repo_root / Path(fixture_name)).resolve()
        fixture_lines = load_fixture_lines(fixture)
        subsets = build_subsets(fixture_lines)
        damage_payloads = extract_damage_payloads(subsets.get("damage", []), _GLOBAL_RUNTIME.line_parser_cls())
        damage_shape_stats = classify_damage_breakdown_shapes(damage_payloads)
        damage_shape_summary.append(
            {
                "fixture": fixture.name,
                "damage_line_count": len(damage_payloads),
                "single_type_count": damage_shape_stats.single_type_count,
                "multi_type_count": damage_shape_stats.multi_type_count,
                "zero_component_count": damage_shape_stats.zero_component_count,
                "multiword_type_count": damage_shape_stats.multiword_type_count,
            }
        )

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
                non_parser_variants.extend(
                    [
                        ("damage_regex_extract_only", lambda lines=subset_lines: run_damage_regex_extract_only(lines)),
                        ("damage_regex_groups_only", lambda lines=subset_lines: run_damage_regex_groups_only(lines)),
                        (
                            "damage_event_materialize_empty_breakdown",
                            lambda lines=subset_lines: run_damage_event_materialize_empty_breakdown(lines),
                        ),
                        (
                            "damage_event_materialize_no_types",
                            lambda lines=subset_lines: run_damage_event_materialize_no_types(lines),
                        ),
                        (
                            "damage_event_materialize_full",
                            lambda lines=subset_lines: run_damage_event_materialize_full(lines),
                        ),
                        (
                            "damage_event_construct_keywords",
                            lambda lines=subset_lines: run_damage_event_construct_keywords(lines),
                        ),
                        (
                            "damage_event_construct_positional",
                            lambda lines=subset_lines: run_damage_event_construct_positional(lines),
                        ),
                        (
                            "damage_event_construct_prebound_cls",
                            lambda lines=subset_lines: run_damage_event_construct_prebound_cls(lines),
                        ),
                        (
                            "damage_event_construct_prebound_timestamp",
                            lambda lines=subset_lines: run_damage_event_construct_prebound_timestamp(lines),
                        ),
                        (
                            "damage_event_construct_without_line_number",
                            lambda lines=subset_lines: run_damage_event_construct_without_line_number(lines),
                        ),
                        (
                            "damage_parse_plus_materialize",
                            lambda lines=subset_lines: run_damage_parse_plus_materialize(lines),
                        ),
                        (
                            "damage_parse_plus_materialize_fixed_timestamp",
                            lambda lines=subset_lines: run_damage_parse_plus_materialize_fixed_timestamp(lines),
                        ),
                        ("damage_breakdown_split_only", lambda lines=subset_lines: run_damage_breakdown_split_only(lines)),
                        ("damage_breakdown_only", lambda lines=subset_lines: run_damage_breakdown_only(lines)),
                        (
                            "damage_breakdown_parse_single_type",
                            lambda lines=subset_lines: run_damage_breakdown_parse_single_type(lines),
                        ),
                        (
                            "damage_breakdown_parse_multi_type",
                            lambda lines=subset_lines: run_damage_breakdown_parse_multi_type(lines),
                        ),
                        (
                            "damage_breakdown_parse_zero_heavy",
                            lambda lines=subset_lines: run_damage_breakdown_parse_zero_heavy(lines),
                        ),
                    ]
                )

            for variant_name, runner in non_parser_variants:
                median_s, event_count = bench_runner(
                    runner=runner,
                    iterations=args.iterations,
                    warmups=args.warmups,
                )
                effective_line_count = len(subset_lines)
                if variant_name in {
                    "damage_breakdown_only",
                    "damage_breakdown_split_only",
                    "damage_breakdown_parse_single_type",
                    "damage_breakdown_parse_multi_type",
                    "damage_breakdown_parse_zero_heavy",
                }:
                    if variant_name == "damage_breakdown_parse_single_type":
                        effective_line_count = len(_filter_damage_payloads(subset_lines, single_type_only=True))
                    elif variant_name == "damage_breakdown_parse_multi_type":
                        effective_line_count = len(_filter_damage_payloads(subset_lines, multi_type_only=True))
                    elif variant_name == "damage_breakdown_parse_zero_heavy":
                        effective_line_count = len(_filter_damage_payloads(subset_lines, zero_component_only=True))
                    else:
                        effective_line_count = len(extract_damage_breakdowns(subset_lines, _GLOBAL_RUNTIME.line_parser_cls()))
                if variant_name in {
                    "damage_regex_extract_only",
                    "damage_regex_groups_only",
                    "damage_event_materialize_empty_breakdown",
                    "damage_event_materialize_no_types",
                    "damage_event_materialize_full",
                    "damage_event_construct_keywords",
                    "damage_event_construct_positional",
                    "damage_event_construct_prebound_cls",
                    "damage_event_construct_prebound_timestamp",
                    "damage_event_construct_without_line_number",
                    "damage_parse_plus_materialize",
                    "damage_parse_plus_materialize_fixed_timestamp",
                }:
                    effective_line_count = len(extract_damage_payloads(subset_lines, _GLOBAL_RUNTIME.line_parser_cls()))
                if variant_name in {
                    "damage_regex_extract_only",
                    "damage_regex_groups_only",
                    "damage_event_materialize_empty_breakdown",
                    "damage_event_materialize_no_types",
                    "damage_event_materialize_full",
                    "damage_event_construct_keywords",
                    "damage_event_construct_positional",
                    "damage_event_construct_prebound_cls",
                    "damage_event_construct_prebound_timestamp",
                    "damage_event_construct_without_line_number",
                    "damage_parse_plus_materialize",
                    "damage_parse_plus_materialize_fixed_timestamp",
                } and event_count != len(extract_damage_payloads(subset_lines, _GLOBAL_RUNTIME.line_parser_cls())):
                    raise RuntimeError(
                        f"damage comparable count drift for {fixture.name} {variant_name}: "
                        f"expected {len(extract_damage_payloads(subset_lines, _GLOBAL_RUNTIME.line_parser_cls()))}, got {event_count}"
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

    print()
    print("Damage path summary")
    damage_headers = (
        "fixture",
        "damage_session_ns",
        "damage_wrapper_ns",
        "damage_regex_extract_ns",
        "damage_regex_groups_ns",
        "damage_event_empty_ns",
        "damage_event_no_types_ns",
        "damage_event_full_ns",
        "damage_breakdown_ns",
        "damage_parse_plus_materialize_ns",
        "damage_parse_plus_materialize_fixed_ts_ns",
        "dominant_cost",
        "single_type_pct",
        "multi_type_pct",
        "zero_component_pct",
        "multiword_type_pct",
    )
    damage_widths = {header: len(header) for header in damage_headers}
    damage_rows: list[dict[str, str]] = []
    for summary in damage_shape_summary:
        fixture_name = str(summary["fixture"])
        session_row = row_map.get((fixture_name, "damage", "parse_immunity=on", "session_full"))
        wrapper_row = row_map.get((fixture_name, "damage", "parse_immunity=on", "session_wrapper_only"))
        extract_row = row_map.get((fixture_name, "damage", "n/a", "damage_regex_extract_only"))
        groups_row = row_map.get((fixture_name, "damage", "n/a", "damage_regex_groups_only"))
        event_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_materialize_empty_breakdown"))
        event_no_types_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_materialize_no_types"))
        event_full_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_materialize_full"))
        breakdown_row = row_map.get((fixture_name, "damage", "n/a", "damage_breakdown_only"))
        parse_plus_materialize_row = row_map.get((fixture_name, "damage", "n/a", "damage_parse_plus_materialize"))
        parse_plus_materialize_fixed_ts_row = row_map.get((fixture_name, "damage", "n/a", "damage_parse_plus_materialize_fixed_timestamp"))
        if not all(
            (
                session_row,
                wrapper_row,
                extract_row,
                groups_row,
                event_row,
                event_no_types_row,
                event_full_row,
                breakdown_row,
                parse_plus_materialize_row,
                parse_plus_materialize_fixed_ts_row,
            )
        ):
            continue
        total = int(summary["damage_line_count"])
        dominant_name, dominant_value = max(
            (
                ("event_full", event_full_row.ns_per_line),
                ("parse_plus_materialize", parse_plus_materialize_row.ns_per_line),
                ("breakdown", breakdown_row.ns_per_line),
                ("session", session_row.ns_per_line),
            ),
            key=lambda item: item[1],
        )
        formatted = {
            "fixture": fixture_name,
            "damage_session_ns": format_ratio(session_row.ns_per_line),
            "damage_wrapper_ns": format_ratio(wrapper_row.ns_per_line),
            "damage_regex_extract_ns": format_ratio(extract_row.ns_per_line),
            "damage_regex_groups_ns": format_ratio(groups_row.ns_per_line),
            "damage_event_empty_ns": format_ratio(event_row.ns_per_line),
            "damage_event_no_types_ns": format_ratio(event_no_types_row.ns_per_line),
            "damage_event_full_ns": format_ratio(event_full_row.ns_per_line),
            "damage_breakdown_ns": format_ratio(breakdown_row.ns_per_line),
            "damage_parse_plus_materialize_ns": format_ratio(parse_plus_materialize_row.ns_per_line),
            "damage_parse_plus_materialize_fixed_ts_ns": format_ratio(parse_plus_materialize_fixed_ts_row.ns_per_line),
            "dominant_cost": f"{dominant_name}:{dominant_value:.1f}",
            "single_type_pct": format_ratio(pct_of(int(summary["single_type_count"]), total)),
            "multi_type_pct": format_ratio(pct_of(int(summary["multi_type_count"]), total)),
            "zero_component_pct": format_ratio(pct_of(int(summary["zero_component_count"]), total)),
            "multiword_type_pct": format_ratio(pct_of(int(summary["multiword_type_count"]), total)),
        }
        damage_rows.append(formatted)
        for header, value in formatted.items():
            damage_widths[header] = max(damage_widths[header], len(value))

    print(" ".join(header.ljust(damage_widths[header]) for header in damage_headers))
    print(" ".join("-" * damage_widths[header] for header in damage_headers))
    for row in damage_rows:
        print(" ".join(row[header].ljust(damage_widths[header]) for header in damage_headers))

    print()
    print("Damage event construction summary")
    construction_headers = (
        "fixture",
        "keywords_ns",
        "positional_ns",
        "prebound_cls_ns",
        "prebound_ts_ns",
        "without_line_ns",
        "best_variant",
        "line_number_cost_ns",
    )
    construction_widths = {header: len(header) for header in construction_headers}
    construction_rows: list[dict[str, str]] = []
    for summary in damage_shape_summary:
        fixture_name = str(summary["fixture"])
        keywords_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_construct_keywords"))
        positional_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_construct_positional"))
        prebound_cls_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_construct_prebound_cls"))
        prebound_ts_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_construct_prebound_timestamp"))
        without_line_row = row_map.get((fixture_name, "damage", "n/a", "damage_event_construct_without_line_number"))
        if not all((keywords_row, positional_row, prebound_cls_row, prebound_ts_row, without_line_row)):
            continue
        best_name, best_row = min(
            (
                ("keywords", keywords_row),
                ("positional", positional_row),
                ("prebound_cls", prebound_cls_row),
                ("prebound_ts", prebound_ts_row),
            ),
            key=lambda item: item[1].ns_per_line,
        )
        formatted = {
            "fixture": fixture_name,
            "keywords_ns": format_ratio(keywords_row.ns_per_line),
            "positional_ns": format_ratio(positional_row.ns_per_line),
            "prebound_cls_ns": format_ratio(prebound_cls_row.ns_per_line),
            "prebound_ts_ns": format_ratio(prebound_ts_row.ns_per_line),
            "without_line_ns": format_ratio(without_line_row.ns_per_line),
            "best_variant": best_name,
            "line_number_cost_ns": format_ratio(prebound_ts_row.ns_per_line - without_line_row.ns_per_line),
        }
        construction_rows.append(formatted)
        for header, value in formatted.items():
            construction_widths[header] = max(construction_widths[header], len(value))

    print(" ".join(header.ljust(construction_widths[header]) for header in construction_headers))
    print(" ".join("-" * construction_widths[header] for header in construction_headers))
    for row in construction_rows:
        print(" ".join(row[header].ljust(construction_widths[header]) for header in construction_headers))

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
                    "damage_shape_summary": damage_shape_summary,
                    "damage_path_summary": damage_rows,
                    "damage_event_construction_summary": construction_rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
