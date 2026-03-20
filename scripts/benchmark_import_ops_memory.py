"""Benchmark import ops memory for materialized-vs-streaming strategies."""

from __future__ import annotations

import argparse
import importlib
import statistics
import sys
import tracemalloc
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)

OPS_KEYS = ("mutations", "death_snippets")


def _peak_mib(run_once) -> float:
    tracemalloc.start()
    run_once()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / (1024 * 1024)


def _normalize_damage_types(raw_damage_types: dict[str, Any]) -> dict[str, int]:
    return {key: int(value or 0) for key, value in raw_damage_types.items()}


def _clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def _load_parser_cls(repo_root: Path) -> type:
    _clear_app_modules()
    repo_root_str = str(repo_root)
    if repo_root_str in sys.path:
        sys.path.remove(repo_root_str)
    sys.path.insert(0, repo_root_str)
    parser_mod = importlib.import_module("app.parser")
    return getattr(parser_mod, "LogParser")


def _event_get(parsed_data: Any, key: str, default: Any = None) -> Any:
    if isinstance(parsed_data, dict):
        return parsed_data.get(key, default)
    return getattr(parsed_data, key, default)


def _append_parsed_op(
    parsed_data: Any,
    mutations: list[dict[str, Any]],
    death_snippets: list[dict[str, Any]],
    last_damage_dealt: dict[str, dict[str, dict[str, int]]],
) -> None:
    event_type = _event_get(parsed_data, "type")

    if event_type == "damage_dealt":
        target = _event_get(parsed_data, "target")
        attacker = _event_get(parsed_data, "attacker")
        timestamp = _event_get(parsed_data, "timestamp")
        total_damage = int(_event_get(parsed_data, "total_damage", 0) or 0)
        damage_types = _normalize_damage_types(dict(_event_get(parsed_data, "damage_types", {}) or {}))

        mutations.append(
            {
                "kind": "damage",
                "target": target,
                "total_damage": total_damage,
                "attacker": attacker,
                "timestamp": timestamp,
                "count_for_dps": True,
                "damage_types": damage_types,
            }
        )
        for damage_type, amount in damage_types.items():
            mutations.append(
                {
                    "kind": "damage",
                    "target": target,
                    "damage_type": damage_type,
                    "total_damage": amount,
                    "attacker": attacker,
                    "timestamp": timestamp,
                    "count_for_dps": False,
                }
            )

        last_damage_dealt[target] = {"damage_types": damage_types}
        return

    if event_type == "immunity":
        target = _event_get(parsed_data, "target")
        damage_type = _event_get(parsed_data, "damage_type")
        if target in last_damage_dealt and damage_type in last_damage_dealt[target]["damage_types"]:
            mutations.append(
                {
                    "kind": "immunity",
                    "target": target,
                    "damage_type": damage_type,
                    "immunity_points": int(_event_get(parsed_data, "immunity_points", 0) or 0),
                    "damage_dealt": last_damage_dealt[target]["damage_types"][damage_type],
                }
            )
        return

    if event_type in {"attack_hit", "attack_hit_critical", "attack_miss"}:
        mutations.append(
            {
                "kind": "attack",
                "attacker": _event_get(parsed_data, "attacker"),
                "target": _event_get(parsed_data, "target"),
                "outcome": (
                    "critical_hit"
                    if event_type == "attack_hit_critical"
                    else ("hit" if event_type == "attack_hit" else "miss")
                ),
                "roll": _event_get(parsed_data, "roll"),
                "bonus": _event_get(parsed_data, "bonus"),
                "total": _event_get(parsed_data, "total"),
                "was_nat1": bool(_event_get(parsed_data, "was_nat1", False)),
                "was_nat20": bool(_event_get(parsed_data, "was_nat20", False)),
                "is_concealment": bool(_event_get(parsed_data, "is_concealment", False)),
            }
        )
        return

    if event_type == "save":
        mutations.append(
            {
                "kind": "save",
                "target": _event_get(parsed_data, "target"),
                "save_key": _event_get(parsed_data, "save_type"),
                "bonus": int(_event_get(parsed_data, "bonus", 0) or 0),
            }
        )
        return

    if event_type == "epic_dodge":
        mutations.append({"kind": "epic_dodge", "target": _event_get(parsed_data, "target")})
        return

    if event_type == "death_snippet":
        death_snippets.append(
            {
                "type": "death_snippet",
                "target": _event_get(parsed_data, "target", ""),
                "killer": _event_get(parsed_data, "killer", ""),
                "lines": list(_event_get(parsed_data, "lines", []) or []),
                "timestamp": _event_get(parsed_data, "timestamp"),
            }
        )


def _iter_file_ops_chunks(path: str | Path, parse_immunity: bool, chunk_size: int, parser_cls: type) -> Any:
    parser = parser_cls(parse_immunity=parse_immunity)
    path = Path(path)
    chunk_size = max(1, int(chunk_size))
    pending_mutations: list[dict[str, Any]] = []
    pending_death_snippets: list[dict[str, Any]] = []
    last_damage_dealt: dict[str, dict[str, dict[str, int]]] = {}

    def flush_pending(force: bool = False) -> Any:
        nonlocal pending_mutations, pending_death_snippets
        while (
            len(pending_mutations) >= chunk_size
            or len(pending_death_snippets) >= chunk_size
            or (force and (pending_mutations or pending_death_snippets))
        ):
            yield {
                "mutations": pending_mutations[:chunk_size],
                "death_snippets": pending_death_snippets[:chunk_size],
            }
            pending_mutations = pending_mutations[chunk_size:]
            pending_death_snippets = pending_death_snippets[chunk_size:]

    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            parsed_data = parser.parse_line(line)
            if not parsed_data:
                continue
            _append_parsed_op(parsed_data, pending_mutations, pending_death_snippets, last_damage_dealt)
            yield from flush_pending()

    yield from flush_pending(force=True)


def _consume_streaming(path: Path, parse_immunity: bool, chunk_size: int, parser_cls: type) -> int:
    consumed = 0
    for chunk in _iter_file_ops_chunks(
        str(path),
        parse_immunity=parse_immunity,
        chunk_size=chunk_size,
        parser_cls=parser_cls,
    ):
        for key in OPS_KEYS:
            consumed += len(chunk.get(key, []))
    return consumed


def _consume_materialized(path: Path, parse_immunity: bool, chunk_size: int, parser_cls: type) -> int:
    all_ops = {key: [] for key in OPS_KEYS}
    for chunk in _iter_file_ops_chunks(
        str(path),
        parse_immunity=parse_immunity,
        chunk_size=10**9,
        parser_cls=parser_cls,
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
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repo root to benchmark.",
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
    repo_root = args.repo_root.resolve()
    parser_cls = _load_parser_cls(repo_root)
    fixtures = [(repo_root / Path(path)).resolve() for path in args.fixtures]

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
                _peak_mib(lambda fixture=fixture, parse_immunity=parse_immunity: _consume_streaming(
                    fixture,
                    parse_immunity,
                    args.chunk_size,
                    parser_cls,
                ))
                for _ in range(args.iterations)
            ]
            materialized_values = [
                _peak_mib(lambda fixture=fixture, parse_immunity=parse_immunity: _consume_materialized(
                    fixture,
                    parse_immunity,
                    args.chunk_size,
                    parser_cls,
                ))
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
