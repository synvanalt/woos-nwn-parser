"""Benchmark Tk panel refresh paths after importing fixture logs."""

from __future__ import annotations

import argparse
import statistics
import sys
import tkinter as tk
from pathlib import Path
from time import perf_counter

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.parser import LogParser
from app.storage import DataStore
from app.services.dps_service import DPSCalculationService
from app.ui.widgets.dps_panel import DPSPanel
from app.ui.widgets.immunity_panel import ImmunityPanel
from app.ui.widgets.target_stats_panel import TargetStatsPanel
from app.utils import parse_and_import_file


DEFAULT_FIXTURES = (
    Path("tests/fixtures/nwclientLog1.txt"),
    Path("tests/fixtures/nwclientLog2.txt"),
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Benchmark UI panel refresh times.")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument(
        "--fixtures",
        nargs="*",
        default=[str(path) for path in DEFAULT_FIXTURES],
    )
    parser.add_argument(
        "--parse-immunity",
        action="store_true",
        help="Import fixture data with immunity parsing enabled.",
    )
    return parser.parse_args()


def timed_refresh(callback, root: tk.Tk) -> float:
    """Measure one widget refresh including idle layout work."""
    started = perf_counter()
    callback()
    root.update_idletasks()
    return perf_counter() - started


def run_panel_benchmarks(fixture: Path, parse_immunity: bool, iterations: int, warmups: int) -> list[dict[str, object]]:
    """Populate store from one fixture and benchmark panel refresh calls."""
    parser = LogParser(parse_immunity=parse_immunity)
    store = DataStore()
    result = parse_and_import_file(str(fixture), parser, store)
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Import failed"))

    root = tk.Tk()
    root.withdraw()
    notebook = tk.ttk.Notebook(root)

    dps_service = DPSCalculationService(store)
    dps_panel = DPSPanel(notebook, store, dps_service)
    immunity_panel = ImmunityPanel(notebook, store, parser)
    target_stats_panel = TargetStatsPanel(notebook, store, parser)

    targets = store.get_all_targets()
    if targets:
        immunity_panel.target_combo.set(targets[0])

    cases = [
        ("dps_refresh", dps_panel.refresh),
        ("target_stats_refresh", target_stats_panel.refresh),
    ]
    if targets:
        selected_target = targets[0]
        cases.append((
            "dps_refresh_target",
            lambda: (
                dps_panel.target_filter_var.set(selected_target),
                dps_panel.refresh(),
            )[-1],
        ))
        cases.append(
            ("immunity_refresh", lambda: immunity_panel.refresh_target_details(selected_target))
        )

    rows: list[dict[str, object]] = []
    for label, callback in cases:
        for _ in range(warmups):
            callback()
            root.update_idletasks()

        timings = [timed_refresh(callback, root) for _ in range(iterations)]
        rows.append({
            "file": fixture.name,
            "mode": "parse_immunity=on" if parse_immunity else "parse_immunity=off",
            "panel": label,
            "median_ms": statistics.median(timings) * 1000.0,
        })

    root.destroy()
    return rows


def main() -> None:
    """Run the UI refresh benchmark suite."""
    args = parse_args()
    fixtures = [Path(path) for path in args.fixtures]

    rows: list[dict[str, object]] = []
    for fixture in fixtures:
        rows.extend(
            run_panel_benchmarks(
                fixture=fixture,
                parse_immunity=args.parse_immunity,
                iterations=args.iterations,
                warmups=args.warmups,
            )
        )

    headers = ("file", "mode", "panel", "median_ms")
    widths = {header: len(header) for header in headers}
    formatted = []
    for row in rows:
        values = {
            "file": str(row["file"]),
            "mode": str(row["mode"]),
            "panel": str(row["panel"]),
            "median_ms": f"{row['median_ms']:.3f}",
        }
        formatted.append(values)
        for header, value in values.items():
            widths[header] = max(widths[header], len(value))

    print("UI refresh benchmark")
    print(f"Iterations: {args.iterations} measured, {args.warmups} warmup")
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()
