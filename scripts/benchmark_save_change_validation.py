"""Run repeated quiet benchmark comparisons for the save-path change."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_BASELINE = REPO_ROOT / "scripts" / "benchmark_baseline.py"
BENCH_COMPONENTS = REPO_ROOT / "scripts" / "benchmark_parser_component_costs.py"
DEFAULT_FIXTURES = (
    "tests/fixtures/real_flurry_conceal_epicdodge.txt",
    "tests/fixtures/real_deadwyrm_offhand_crit_mix.txt",
    "tests/fixtures/real_tod_risen_save_dense.txt",
)


@dataclass(frozen=True)
class BenchTarget:
    label: str
    repo_root: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the save-path benchmark delta quietly.")
    parser.add_argument("--before-repo-root", type=Path, required=True)
    parser.add_argument("--after-repo-root", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--large-fixture-iterations", type=int, default=12)
    parser.add_argument("--parse-immunity-mode", choices=("off", "on", "both"), default="on")
    parser.add_argument("--cooldown-seconds", type=float, default=5.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "bench_compare",
    )
    return parser.parse_args()


def run_process(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def detect_other_benchmark_processes() -> tuple[list[dict[str, Any]], str | None]:
    current_pid = os.getpid()
    command = (
        f"$selfPid = {current_pid}; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.ProcessId -ne $selfPid -and $_.CommandLine -match 'benchmark_' } | "
        "Select-Object ProcessId, Name, CommandLine | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "process enumeration failed"
        return [], stderr
    raw = completed.stdout.strip()
    if not raw:
        return [], None
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        return [parsed], None
    return list(parsed), None


def run_baseline(
    target: BenchTarget,
    *,
    json_out: Path,
    iterations: int,
    warmups: int,
    large_fixture_iterations: int,
    parse_immunity_mode: str,
) -> None:
    command = [
        sys.executable,
        str(BENCH_BASELINE),
        "--repo-root",
        str(target.repo_root),
        "--iterations",
        str(iterations),
        "--warmups",
        str(warmups),
        "--large-fixture-iterations",
        str(large_fixture_iterations),
        "--parse-immunity-mode",
        parse_immunity_mode,
        "--json-out",
        str(json_out),
    ]
    run_process(command, cwd=REPO_ROOT)


def run_component_costs(
    target: BenchTarget,
    *,
    json_out: Path,
    iterations: int,
    warmups: int,
) -> None:
    command = [
        sys.executable,
        str(BENCH_COMPONENTS),
        "--repo-root",
        str(target.repo_root),
        "--iterations",
        str(iterations),
        "--warmups",
        str(warmups),
        "--json-out",
        str(json_out),
    ]
    run_process(command, cwd=REPO_ROOT)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def select_baseline_row(rows: list[dict[str, Any]], fixture: str, layer: str, mode: str) -> dict[str, Any]:
    for row in rows:
        if row["file"] == fixture and row["layer"] == layer and row["mode"] == mode:
            return row
    raise RuntimeError(f"missing baseline row for {fixture} {layer} {mode}")


def select_component_row(
    rows: list[dict[str, Any]],
    fixture: str,
    subset: str,
    variant: str,
    mode: str,
) -> dict[str, Any]:
    for row in rows:
        if (
            row["fixture"] == fixture
            and row["subset"] == subset
            and row["variant"] == variant
            and row["mode"] == mode
        ):
            return row
    raise RuntimeError(f"missing component row for {fixture} {subset} {variant} {mode}")


def median_of(values: list[float]) -> float:
    return float(median(values))


def spread_pct(values: list[float]) -> float:
    if not values:
        return 0.0
    med = median_of(values)
    if med <= 0:
        return 0.0
    return ((max(values) - min(values)) / med) * 100.0


def sign_consistency(deltas: list[float]) -> str:
    pos = sum(1 for value in deltas if value > 0)
    neg = sum(1 for value in deltas if value < 0)
    zero = sum(1 for value in deltas if value == 0)
    return f"+{pos}/-{neg}/0{zero}"


def main() -> None:
    args = parse_args()
    before_root = args.before_repo_root.resolve()
    after_root = args.after_repo_root.resolve()
    if not before_root.is_dir():
        raise RuntimeError(f"before repo root not found: {before_root}")
    if not after_root.is_dir():
        raise RuntimeError(f"after repo root not found: {after_root}")

    other_processes, preflight_warning = detect_other_benchmark_processes()
    if other_processes:
        raise RuntimeError(
            "Refusing to start while other benchmark processes are running:\n"
            + "\n".join(
                f"{proc.get('ProcessId')} {proc.get('Name')}: {proc.get('CommandLine')}"
                for proc in other_processes
            )
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir / f"save_change_validation_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Save change validation")
    print(f"Before: {before_root}")
    print(f"After:  {after_root}")
    print(f"Rounds: {args.rounds}")
    print(f"Output: {output_dir}")
    if preflight_warning:
        print(f"Preflight warning: benchmark process enumeration unavailable ({preflight_warning})")
    else:
        print("Preflight: no other benchmark_* processes detected")
    print()

    targets = (
        BenchTarget("before", before_root),
        BenchTarget("after", after_root),
    )
    round_results: list[dict[str, Any]] = []
    for round_index in range(1, args.rounds + 1):
        round_dir = output_dir / f"round_{round_index:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        print(f"Round {round_index}/{args.rounds}")
        for target in targets:
            baseline_json = round_dir / f"{target.label}_baseline.json"
            components_json = round_dir / f"{target.label}_components.json"
            run_baseline(
                target,
                json_out=baseline_json,
                iterations=args.iterations,
                warmups=args.warmups,
                large_fixture_iterations=args.large_fixture_iterations,
                parse_immunity_mode=args.parse_immunity_mode,
            )
            run_component_costs(
                target,
                json_out=components_json,
                iterations=args.iterations,
                warmups=args.warmups,
            )
        round_results.append(
            {
                "round": round_index,
                "before_baseline": load_json(round_dir / "before_baseline.json"),
                "after_baseline": load_json(round_dir / "after_baseline.json"),
                "before_components": load_json(round_dir / "before_components.json"),
                "after_components": load_json(round_dir / "after_components.json"),
            }
        )
        if round_index < args.rounds:
            time.sleep(max(0.0, args.cooldown_seconds))

    summary_rows: list[dict[str, Any]] = []
    for fixture in DEFAULT_FIXTURES:
        fixture_name = Path(fixture).name
        for layer in ("parser_only", "full_import"):
            before_values = [
                select_baseline_row(result["before_baseline"]["rows"], fixture_name, layer, "parse_immunity=on")["median_s"]
                for result in round_results
            ]
            after_values = [
                select_baseline_row(result["after_baseline"]["rows"], fixture_name, layer, "parse_immunity=on")["median_s"]
                for result in round_results
            ]
            deltas = [after - before for before, after in zip(before_values, after_values)]
            summary_rows.append(
                {
                    "fixture": fixture_name,
                    "metric": layer,
                    "before_median_of_medians": median_of(before_values),
                    "after_median_of_medians": median_of(after_values),
                    "delta_s": median_of(deltas),
                    "before_spread_pct": spread_pct(before_values),
                    "after_spread_pct": spread_pct(after_values),
                    "sign_consistency": sign_consistency(deltas),
                }
            )

        before_save_counts = [
            select_component_row(
                result["before_components"]["rows"],
                fixture_name,
                "save",
                "session_full",
                "parse_immunity=on",
            )["event_count"]
            for result in round_results
        ]
        after_save_counts = [
            select_component_row(
                result["after_components"]["rows"],
                fixture_name,
                "save",
                "session_full",
                "parse_immunity=on",
            )["event_count"]
            for result in round_results
        ]
        before_save_ns = [
            select_component_row(
                result["before_components"]["rows"],
                fixture_name,
                "save",
                "session_full",
                "parse_immunity=on",
            )["ns_per_line"]
            for result in round_results
        ]
        after_save_ns = [
            select_component_row(
                result["after_components"]["rows"],
                fixture_name,
                "save",
                "session_full",
                "parse_immunity=on",
            )["ns_per_line"]
            for result in round_results
        ]
        summary_rows.append(
            {
                "fixture": fixture_name,
                "metric": "save_event_count",
                "before_median_of_medians": median_of([float(v) for v in before_save_counts]),
                "after_median_of_medians": median_of([float(v) for v in after_save_counts]),
                "delta_s": median_of([float(a - b) for b, a in zip(before_save_counts, after_save_counts)]),
                "before_spread_pct": spread_pct([float(v) for v in before_save_counts]),
                "after_spread_pct": spread_pct([float(v) for v in after_save_counts]),
                "sign_consistency": sign_consistency([float(a - b) for b, a in zip(before_save_counts, after_save_counts)]),
            }
        )
        summary_rows.append(
            {
                "fixture": fixture_name,
                "metric": "save_ns_per_line",
                "before_median_of_medians": median_of(before_save_ns),
                "after_median_of_medians": median_of(after_save_ns),
                "delta_s": median_of([after - before for before, after in zip(before_save_ns, after_save_ns)]),
                "before_spread_pct": spread_pct(before_save_ns),
                "after_spread_pct": spread_pct(after_save_ns),
                "sign_consistency": sign_consistency([after - before for before, after in zip(before_save_ns, after_save_ns)]),
            }
        )

    decision_lines: list[str] = []
    heavy_fixtures = {"real_deadwyrm_offhand_crit_mix.txt", "real_tod_risen_save_dense.txt"}
    improved_save_counts = all(
        row["after_median_of_medians"] >= row["before_median_of_medians"]
        for row in summary_rows
        if row["metric"] == "save_event_count"
    )
    improved_heavy_save_ns = all(
        row["after_median_of_medians"] < row["before_median_of_medians"]
        for row in summary_rows
        if row["metric"] == "save_ns_per_line" and row["fixture"] in heavy_fixtures
    )
    parser_only_consistent = all(
        row["sign_consistency"].startswith("+0/-") or row["sign_consistency"] in {"+0/-5/00", "+0/-4/01"}
        for row in summary_rows
        if row["metric"] == "parser_only"
    )
    full_import_not_worse = all(
        row["after_spread_pct"] < 50.0 or row["delta_s"] <= 0
        for row in summary_rows
        if row["metric"] == "full_import"
    )
    if improved_save_counts and improved_heavy_save_ns and parser_only_consistent and full_import_not_worse:
        conclusion = "confirmed win"
    elif any(row["after_spread_pct"] > 50.0 for row in summary_rows if row["metric"] in {"parser_only", "full_import"}):
        conclusion = "inconclusive due to benchmark instability"
    else:
        conclusion = "confirmed regression"
    decision_lines.append(conclusion)

    report = {
        "before_repo_root": str(before_root),
        "after_repo_root": str(after_root),
        "rounds": args.rounds,
        "iterations": args.iterations,
        "warmups": args.warmups,
        "large_fixture_iterations": args.large_fixture_iterations,
        "parse_immunity_mode": args.parse_immunity_mode,
        "cooldown_seconds": args.cooldown_seconds,
        "summary_rows": summary_rows,
        "conclusion": conclusion,
    }
    report_path = output_dir / "summary.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md_lines = [
        "# Save Change Validation",
        "",
        f"- Before: `{before_root}`",
        f"- After: `{after_root}`",
        f"- Rounds: `{args.rounds}`",
        f"- Conclusion: `{conclusion}`",
        "",
        "| Fixture | Metric | Before median | After median | Delta | Before spread | After spread | Signs |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary_rows:
        md_lines.append(
            f"| {row['fixture']} | {row['metric']} | "
            f"{row['before_median_of_medians']:.4f} | {row['after_median_of_medians']:.4f} | "
            f"{row['delta_s']:.4f} | {row['before_spread_pct']:.1f}% | "
            f"{row['after_spread_pct']:.1f}% | {row['sign_consistency']} |"
        )
    (output_dir / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Completed. Summary: {output_dir / 'summary.md'}")
    print(f"Conclusion: {conclusion}")


if __name__ == "__main__":
    main()
