"""Benchmark parser cost by line category on fixture logs."""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from time import perf_counter

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.parser import ParserSession


DEFAULT_FIXTURES = (
    Path("tests/fixtures/real_flurry_conceal_epicdodge.txt"),
    Path("tests/fixtures/real_deadwyrm_offhand_crit_mix.txt"),
    Path("tests/fixtures/real_tod_risen_save_dense.txt"),
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Benchmark parser hotspots by line category.")
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--fixtures",
        nargs="*",
        default=[str(path) for path in DEFAULT_FIXTURES],
    )
    return parser.parse_args()


def classify_line(line: str) -> str:
    """Classify a log line into one parser cost bucket."""
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


def load_grouped_lines(path: Path) -> dict[str, list[str]]:
    """Load one fixture and group its lines by parser category."""
    grouped: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            category = classify_line(line)
            grouped.setdefault(category, []).append(line)
    return grouped


def time_category(lines: list[str], parse_immunity: bool, iterations: int, warmups: int) -> dict[str, float]:
    """Measure parser throughput for one category."""
    if not lines:
        return {"median_s": 0.0, "lines_per_s": 0.0, "ns_per_line": 0.0}

    def run_once() -> float:
        parser = ParserSession(parse_immunity=parse_immunity)
        started = perf_counter()
        for line in lines:
            parser.parse_line(line)
        return perf_counter() - started

    for _ in range(warmups):
        run_once()

    timings = [run_once() for _ in range(iterations)]
    median_s = float(statistics.median(timings))
    lines_per_s = len(lines) / median_s if median_s > 0 else 0.0
    ns_per_line = (median_s / len(lines)) * 1_000_000_000 if lines else 0.0
    return {
        "median_s": median_s,
        "lines_per_s": lines_per_s,
        "ns_per_line": ns_per_line,
    }


def main() -> None:
    """Run parser hotspot benchmarks for all fixtures."""
    args = parse_args()
    rows: list[dict[str, object]] = []

    for fixture_name in args.fixtures:
        fixture = Path(fixture_name)
        grouped = load_grouped_lines(fixture)
        for parse_immunity in (False, True):
            for category in sorted(grouped):
                lines = grouped[category]
                result = time_category(lines, parse_immunity, args.iterations, args.warmups)
                rows.append({
                    "file": fixture.name,
                    "mode": "parse_immunity=on" if parse_immunity else "parse_immunity=off",
                    "category": category,
                    "line_count": len(lines),
                    "median_s": result["median_s"],
                    "ns_per_line": result["ns_per_line"],
                    "lines_per_s": result["lines_per_s"],
                })

    headers = ("file", "mode", "category", "line_count", "median_s", "ns_per_line", "lines_per_s")
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted = {
            "file": str(row["file"]),
            "mode": str(row["mode"]),
            "category": str(row["category"]),
            "line_count": str(row["line_count"]),
            "median_s": f"{row['median_s']:.4f}",
            "ns_per_line": f"{row['ns_per_line']:.0f}",
            "lines_per_s": f"{row['lines_per_s']:.0f}",
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Parser hotspot benchmark")
    print(f"Iterations: {args.iterations} measured, {args.warmups} warmup")
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted_rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()
