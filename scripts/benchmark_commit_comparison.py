"""Run the benchmark suite across selected commits and generate a comparison report."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMMITS = (
    ("baseline", "19ddc5e"),
    ("post_ingestion_unification", "f654523"),
    ("post_typed_event_models", "9371bf9"),
    ("post_main_window_decompose", "10a762e"),
)

BENCHMARKS = (
    {
        "id": "baseline",
        "title": "Baseline parser/import throughput",
        "script": Path("scripts/benchmark_baseline.py"),
        "args": (
            "--iterations",
            "{iterations}",
            "--warmups",
            "{warmups}",
            "--large-fixture-iterations",
            "{iterations}",
            "--repo-root",
            "{repo_root}",
            "--parse-immunity-mode",
            "on",
        ),
        "metric": "median_s",
        "smaller_is_better": True,
        "notes": "Compares parser-only and full-import medians for each fixture with parse_immunity=on.",
        "run_from_main_repo": True,
    },
    {
        "id": "parser_hotspots",
        "title": "Parser hotspot throughput",
        "script": Path("scripts/benchmark_parser_hotspots.py"),
        "args": ("--iterations", "{iterations}", "--warmups", "{warmups}"),
        "metric": "median_s",
        "smaller_is_better": True,
        "notes": "Breaks parser cost down by log-line category for each fixture and immunity mode.",
    },
    {
        "id": "monitor_polling",
        "title": "Monitor polling overhead",
        "script": Path("scripts/benchmark_monitor_polling.py"),
        "args": ("--iterations", "{iterations}", "--warmups", "{warmups}"),
        "metric": "current_us_per_poll",
        "smaller_is_better": True,
        "notes": "Measures current monitor poll cost relative to the benchmark's built-in legacy comparator.",
    },
    {
        "id": "import_ipc",
        "title": "Import IPC worker and queue throughput",
        "script": Path("scripts/benchmark_import_ipc.py"),
        "args": ("--iterations", "{iterations}", "--warmups", "{warmups}"),
        "metric": "median_s",
        "smaller_is_better": True,
        "notes": "Measures the multiprocessing import worker and queue path for each fixture and immunity mode.",
    },
    {
        "id": "import_ops_memory",
        "title": "Import ops peak memory",
        "script": Path("scripts/benchmark_import_ops_memory.py"),
        "args": ("--iterations", "{iterations}", "--repo-root", "{repo_root}"),
        "metric": "stream_peak_mib",
        "smaller_is_better": True,
        "notes": "Tracks streaming import peak tracemalloc memory; materialized-vs-streaming delta remains in raw output.",
        "run_from_main_repo": True,
    },
    {
        "id": "read_refresh",
        "title": "Read-refresh service cost",
        "script": Path("scripts/benchmark_read_refresh.py"),
        "args": (
            "--iterations",
            "{iterations}",
            "--warmups",
            "{warmups}",
            "--large-fixture-iterations",
            "{iterations}",
        ),
        "metric": "median_ms",
        "smaller_is_better": True,
        "notes": "Measures steady-state and live-refresh read bundles with cache on/off.",
    },
    {
        "id": "ui_refresh",
        "title": "UI panel refresh cost",
        "script": Path("scripts/benchmark_ui_refresh.py"),
        "args": ("--iterations", "{iterations}", "--warmups", "{warmups}"),
        "metric": "median_ms",
        "smaller_is_better": True,
        "notes": "Measures panel refresh medians after fixture import in the commit's Tk UI.",
    },
    {
        "id": "ui_refresh_parse_immunity_on",
        "title": "UI panel refresh cost (parse immunity on)",
        "script": Path("scripts/benchmark_ui_refresh.py"),
        "args": ("--iterations", "{iterations}", "--warmups", "{warmups}", "--parse-immunity"),
        "metric": "median_ms",
        "smaller_is_better": True,
        "notes": "Runs the same Tk refresh benchmark with immunity parsing enabled at import time.",
    },
)

FLOAT_COLUMNS = {
    "min_s",
    "median_s",
    "mean_s",
    "max_s",
    "spread_pct",
    "lines_per_s",
    "mb_per_s",
    "median_ms",
    "min_ms",
    "max_ms",
    "refreshes_per_s",
    "ns_per_line",
    "stream_peak_mib",
    "materialized_peak_mib",
    "delta_mib",
    "delta_pct",
    "current_us_per_poll",
    "legacy_us_per_poll",
    "speedup_x",
    "poll_reduction_pct",
}
DERIVED_STRING_COLUMNS = {"speedup_vs_off"}
INT_COLUMNS = {
    "lines",
    "line_count",
    "parsed_events",
    "store_events",
    "store_attacks",
    "dps_entries",
    "immunity_targets",
    "events_seen",
    "chunks_seen",
    "files_completed",
    "ops_items_seen",
    "rows_seen",
    "targets_seen",
    "characters_seen",
}


@dataclass(frozen=True)
class CommitTarget:
    label: str
    revision: str
    worktree: Path


@dataclass(frozen=True)
class BenchmarkRun:
    benchmark_id: str
    commit_label: str
    revision: str
    stdout_path: Path
    stderr_path: Path
    rows: list[dict[str, object]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark selected commits and compare them.")
    parser.add_argument("--iterations", type=int, default=12, help="Measured runs per scenario.")
    parser.add_argument("--warmups", type=int, default=2, help="Warmup runs per scenario when supported.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("bench_compare"),
        help="Directory for raw outputs and generated report.",
    )
    parser.add_argument(
        "--worktree-root",
        type=Path,
        default=Path(".bench_worktrees"),
        help="Directory containing detached benchmark worktrees.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue other benchmarks when one command fails.",
    )
    parser.add_argument(
        "--existing-output-root",
        type=Path,
        help="Reuse an existing benchmark output directory and rebuild the report from its raw files only.",
    )
    parser.add_argument(
        "--benchmark-ids",
        nargs="+",
        help="Optional list of benchmark ids to run/report.",
    )
    return parser.parse_args()


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def ensure_worktree(target: CommitTarget) -> None:
    target.worktree.parent.mkdir(parents=True, exist_ok=True)
    if target.worktree.exists():
        if (target.worktree / ".git").exists():
            return
        raise RuntimeError(f"existing directory at {target.worktree} is not a git worktree")
    run_git("worktree", "add", "--detach", str(target.worktree), target.revision)


def render_command_args(
    template_args: Iterable[str],
    *,
    iterations: int,
    warmups: int,
    repo_root: Path,
) -> list[str]:
    values = {
        "iterations": str(iterations),
        "warmups": str(warmups),
        "repo_root": str(repo_root),
    }
    return [part.format(**values) for part in template_args]


def clean_table_value(value: str) -> object:
    stripped = value.strip()
    if stripped.endswith("%"):
        stripped = stripped[:-1]
    if stripped in {"True", "False"}:
        return stripped == "True"
    if stripped in {"-", ""}:
        return stripped
    return stripped


def coerce_row_types(row: dict[str, object]) -> dict[str, object]:
    converted: dict[str, object] = {}
    for key, value in row.items():
        if not isinstance(value, str):
            converted[key] = value
            continue
        raw = clean_table_value(value)
        if isinstance(raw, bool):
            converted[key] = raw
        elif key in FLOAT_COLUMNS:
            converted[key] = float(raw)
        elif key in INT_COLUMNS:
            converted[key] = int(raw)
        else:
            converted[key] = raw
    return converted


def parse_fixed_width_tables(stdout: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    lines = stdout.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if not line:
            index += 1
            continue
        if index + 1 < len(lines):
            header = line
            separator = lines[index + 1].rstrip()
            if header and separator and set(separator.replace(" ", "")) == {"-"}:
                headers = header.split()
                index += 2
                while index < len(lines):
                    current = lines[index].rstrip()
                    if not current:
                        break
                    if set(current.replace(" ", "")) == {"-"}:
                        break
                    values = current.split()
                    if len(values) == len(headers):
                        rows.append(coerce_row_types(dict(zip(headers, values, strict=True))))
                    index += 1
                continue
        index += 1
    return rows


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def run_benchmark(
    target: CommitTarget,
    benchmark: dict[str, object],
    *,
    iterations: int,
    warmups: int,
    raw_output_root: Path,
) -> BenchmarkRun:
    script = Path(benchmark["script"])
    args = render_command_args(
        benchmark["args"],
        iterations=iterations,
        warmups=warmups,
        repo_root=target.worktree,
    )
    command = [sys.executable, str(script), *args]
    cwd = REPO_ROOT if bool(benchmark.get("run_from_main_repo", False)) else target.worktree
    stdout_path = raw_output_root / f"{target.label}__{benchmark['id']}.txt"
    stderr_path = raw_output_root / f"{target.label}__{benchmark['id']}.stderr.txt"
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
        raise

    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    rows = parse_fixed_width_tables(completed.stdout)
    if not rows:
        raise RuntimeError(f"no benchmark rows parsed for {benchmark['id']} on {target.label}")
    return BenchmarkRun(
        benchmark_id=str(benchmark["id"]),
        commit_label=target.label,
        revision=target.revision,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        rows=rows,
    )


def build_scenario_key(row: dict[str, object], metric: str) -> str:
    ignored = set(FLOAT_COLUMNS) | DERIVED_STRING_COLUMNS | {metric}
    parts = [f"{key}={row[key]}" for key in row if key not in ignored]
    return " | ".join(parts)


def pct_change(current: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return ((current - baseline) / baseline) * 100.0


def improvement_vs_baseline(current: float, baseline: float, *, smaller_is_better: bool) -> float:
    raw = pct_change(current, baseline)
    return -raw if smaller_is_better else raw


def format_metric(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def summarize_benchmark(
    benchmark: dict[str, object],
    runs: list[BenchmarkRun],
    commit_targets: list[CommitTarget],
) -> tuple[str, list[dict[str, object]]]:
    metric = str(benchmark["metric"])
    smaller_is_better = bool(benchmark["smaller_is_better"])
    rows_by_commit = {run.commit_label: run.rows for run in runs}
    scenario_rows: dict[str, dict[str, dict[str, object]]] = {}
    scenario_order: list[str] = []
    baseline_label = commit_targets[0].label

    for row in rows_by_commit[baseline_label]:
        key = build_scenario_key(row, metric)
        scenario_rows[key] = {baseline_label: row}
        scenario_order.append(key)

    for target in commit_targets[1:]:
        for row in rows_by_commit[target.label]:
            key = build_scenario_key(row, metric)
            scenario_rows.setdefault(key, {})
            scenario_rows[key][target.label] = row
            if key not in scenario_order:
                scenario_order.append(key)

    summary_rows: list[dict[str, object]] = []
    markdown_lines = [f"## {benchmark['title']}", "", str(benchmark["notes"]), ""]
    markdown_lines.append("| Scenario | " + " | ".join(f"{target.label} ({target.revision})" for target in commit_targets) + " | Best vs baseline |")
    markdown_lines.append("| --- | " + " | ".join("---" for _ in commit_targets) + " | --- |")

    for scenario_key in scenario_order:
        row_map = scenario_rows[scenario_key]
        baseline_row = row_map.get(baseline_label)
        if baseline_row is None:
            continue
        baseline_value = float(baseline_row[metric])
        best_label = baseline_label
        best_improvement = 0.0
        values: list[str] = []
        for target in commit_targets:
            row = row_map.get(target.label)
            if row is None:
                values.append("n/a")
                continue
            value = float(row[metric])
            if target.label == baseline_label:
                values.append(f"{format_metric(value)} (baseline)")
            else:
                improvement = improvement_vs_baseline(value, baseline_value, smaller_is_better=smaller_is_better)
                delta = pct_change(value, baseline_value)
                values.append(f"{format_metric(value)} ({delta:+.1f}% raw, {improvement:+.1f}% vs base)")
                if improvement > best_improvement:
                    best_improvement = improvement
                    best_label = target.label
            summary_rows.append(
                {
                    "benchmark_id": benchmark["id"],
                    "scenario": scenario_key,
                    "commit": target.label,
                    "revision": target.revision,
                    "metric": metric,
                    "value": value,
                    "pct_vs_baseline": 0.0 if target.label == baseline_label else pct_change(value, baseline_value),
                    "improvement_vs_baseline": 0.0 if target.label == baseline_label else improvement_vs_baseline(
                        value,
                        baseline_value,
                        smaller_is_better=smaller_is_better,
                    ),
                }
            )
        scenario_cell = scenario_key.replace("|", "\\|")
        markdown_lines.append(f"| {scenario_cell} | " + " | ".join(values) + f" | {best_label} ({best_improvement:+.1f}%) |")

    markdown_lines.extend(["", f"Primary comparison metric: `{metric}`.", ""])
    return "\n".join(markdown_lines), summary_rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_executive_summary(summary_rows: list[dict[str, object]], commit_targets: list[CommitTarget]) -> list[str]:
    baseline_label = commit_targets[0].label
    lines = ["# Commit Benchmark Comparison", "", "## Executive summary", ""]
    by_benchmark: dict[str, list[dict[str, object]]] = {}
    for row in summary_rows:
        by_benchmark.setdefault(str(row["benchmark_id"]), []).append(row)

    for benchmark_id, rows in by_benchmark.items():
        non_baseline = [row for row in rows if row["commit"] != baseline_label]
        if not non_baseline:
            continue
        best = max(non_baseline, key=lambda row: float(row["improvement_vs_baseline"]))
        worst = min(non_baseline, key=lambda row: float(row["improvement_vs_baseline"]))
        lines.append(
            f"- `{benchmark_id}`: best improvement was {best['commit']} at {float(best['improvement_vs_baseline']):+.1f}% vs baseline on `{best['scenario']}`; "
            f"worst regression was {worst['commit']} at {float(worst['improvement_vs_baseline']):+.1f}% on `{worst['scenario']}`."
        )
    lines.append("")
    return lines


def load_existing_runs(output_root: Path, commit_targets: list[CommitTarget]) -> list[BenchmarkRun]:
    raw_output_root = output_root / "raw"
    runs: list[BenchmarkRun] = []
    for benchmark in BENCHMARKS:
        benchmark_id = str(benchmark["id"])
        for target in commit_targets:
            stdout_path = raw_output_root / f"{target.label}__{benchmark_id}.txt"
            stderr_path = raw_output_root / f"{target.label}__{benchmark_id}.stderr.txt"
            if not stdout_path.exists():
                continue
            stdout = stdout_path.read_text(encoding="utf-8")
            rows = parse_fixed_width_tables(stdout)
            if not rows:
                raise RuntimeError(f"no benchmark rows parsed from existing raw output {stdout_path}")
            runs.append(
                BenchmarkRun(
                    benchmark_id=benchmark_id,
                    commit_label=target.label,
                    revision=target.revision,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    rows=rows,
                )
            )
    return runs


def select_benchmarks(requested_ids: list[str] | None) -> list[dict[str, object]]:
    if not requested_ids:
        return list(BENCHMARKS)

    by_id = {str(benchmark["id"]): benchmark for benchmark in BENCHMARKS}
    unknown = [benchmark_id for benchmark_id in requested_ids if benchmark_id not in by_id]
    if unknown:
        raise RuntimeError(f"unknown benchmark ids: {', '.join(unknown)}")
    return [by_id[benchmark_id] for benchmark_id in requested_ids]


def main() -> None:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    existing_output_root = args.existing_output_root.resolve() if args.existing_output_root else None
    output_root = existing_output_root or (REPO_ROOT / args.output_root / f"commit_comparison_{timestamp}").resolve()
    raw_output_root = output_root / "raw"
    worktree_root = (REPO_ROOT / args.worktree_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    raw_output_root.mkdir(parents=True, exist_ok=True)

    commit_targets = [
        CommitTarget(label=label, revision=revision, worktree=worktree_root / f"{label}_{revision}")
        for label, revision in DEFAULT_COMMITS
    ]
    selected_benchmarks = select_benchmarks(args.benchmark_ids)

    failures: list[str] = []
    if existing_output_root is None:
        for target in commit_targets:
            ensure_worktree(target)

        all_runs: list[BenchmarkRun] = []
        for benchmark in selected_benchmarks:
            for target in commit_targets:
                try:
                    all_runs.append(
                        run_benchmark(
                            target,
                            benchmark,
                            iterations=args.iterations,
                            warmups=args.warmups,
                            raw_output_root=raw_output_root,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    message = f"{benchmark['id']} on {target.label} ({target.revision}) failed: {exc}"
                    failures.append(message)
                    if not args.keep_going:
                        raise RuntimeError(message) from exc
    else:
        all_runs = load_existing_runs(output_root, commit_targets)
        allowed_ids = {str(benchmark["id"]) for benchmark in selected_benchmarks}
        all_runs = [run for run in all_runs if run.benchmark_id in allowed_ids]

    runs_by_benchmark: dict[str, list[BenchmarkRun]] = {}
    for run in all_runs:
        runs_by_benchmark.setdefault(run.benchmark_id, []).append(run)

    markdown_lines = build_executive_summary([], commit_targets)
    summary_rows: list[dict[str, object]] = []
    for benchmark in selected_benchmarks:
        benchmark_id = str(benchmark["id"])
        runs = runs_by_benchmark.get(benchmark_id, [])
        if len(runs) != len(commit_targets):
            markdown_lines.extend([f"## {benchmark['title']}", "", "Benchmark incomplete for one or more commits.", ""])
            continue
        section_markdown, benchmark_summary_rows = summarize_benchmark(benchmark, runs, commit_targets)
        markdown_lines.append(section_markdown)
        markdown_lines.append("")
        summary_rows.extend(benchmark_summary_rows)

    markdown_lines = build_executive_summary(summary_rows, commit_targets) + markdown_lines[4:]
    if failures:
        markdown_lines.extend(["## Failures", ""])
        markdown_lines.extend(f"- {failure}" for failure in failures)
        markdown_lines.append("")

    report_path = output_root / "commit_comparison_report.md"
    report_path.write_text("\n".join(markdown_lines).rstrip() + "\n", encoding="utf-8")

    write_csv(output_root / "summary.csv", summary_rows)
    manifest = {
        "timestamp": timestamp,
        "output_root": str(output_root),
        "report_path": str(report_path),
        "failures": failures,
        "benchmark_ids": [str(benchmark["id"]) for benchmark in selected_benchmarks],
        "commits": [{"label": target.label, "revision": target.revision, "worktree": str(target.worktree)} for target in commit_targets],
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Results written to: {output_root}")
    print(f"Report: {report_path}")
    if failures:
        print(f"Failures: {len(failures)}")
        for failure in failures:
            print(f"- {failure}")


if __name__ == "__main__":
    main()
