"""Benchmark monitor poll-loop overhead against the legacy discovery flow."""

from __future__ import annotations

import argparse
import queue
import shutil
import statistics
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.monitor import LogDirectoryMonitor


class LegacyLogDirectoryMonitor:
    """Pre-optimization monitor behavior for poll-loop comparison."""

    def __init__(self, log_directory: str) -> None:
        self.log_directory = Path(log_directory)
        self.current_log_file: Optional[Path] = None
        self.last_position = 0
        self.last_mtime = 0.0

    def find_active_log_file(self) -> Optional[Path]:
        if not self.log_directory.exists():
            return None
        log_files = sorted(self.log_directory.glob("nwclientLog[1-4].txt"))
        if not log_files:
            return None
        return max(log_files, key=lambda path: path.stat().st_mtime)

    def get_active_log_file(self) -> Optional[Path]:
        return self.find_active_log_file()

    def start_monitoring(self) -> None:
        self.current_log_file = self.get_active_log_file()
        if self.current_log_file and self.current_log_file.exists():
            stat_result = self.current_log_file.stat()
            self.last_position = stat_result.st_size
            self.last_mtime = stat_result.st_mtime

    def read_new_lines(
        self,
        parser,
        data_queue: queue.Queue,
        on_log_message=None,
        debug_enabled: bool = False,
        max_lines_per_poll: int = 2000,
    ) -> bool:
        try:
            active_file = self.get_active_log_file()
            queue_saturated = False

            if active_file != self.current_log_file:
                self.current_log_file = active_file
                self.last_position = 0

            if not self.current_log_file or not self.current_log_file.exists():
                return False

            stat_result = self.current_log_file.stat()
            current_size = stat_result.st_size
            current_mtime = stat_result.st_mtime

            if current_size < self.last_position:
                self.last_position = 0
                self.last_mtime = current_mtime
            elif current_size == 0 and self.last_position > 0:
                self.last_position = 0
                self.last_mtime = current_mtime

            parsed_lines = 0
            with open(self.current_log_file, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self.last_position)
                if hasattr(handle, "readline"):
                    while parsed_lines < max_lines_per_poll:
                        if getattr(data_queue, "maxsize", 0) > 0 and data_queue.full():
                            queue_saturated = True
                            break
                        line = handle.readline()
                        if not line:
                            break
                        parsed_lines += 1
                        parsed_data = parser.parse_line(line)
                        if parsed_data:
                            try:
                                data_queue.put_nowait(parsed_data)
                            except queue.Full:
                                queue_saturated = True
                                break
                else:
                    lines = list(handle.readlines())[:max_lines_per_poll]
                    for line in lines:
                        if getattr(data_queue, "maxsize", 0) > 0 and data_queue.full():
                            queue_saturated = True
                            break
                        parsed_lines += 1
                        parsed_data = parser.parse_line(line)
                        if parsed_data:
                            try:
                                data_queue.put_nowait(parsed_data)
                            except queue.Full:
                                queue_saturated = True
                                break

                self.last_position = handle.tell()
                self.last_mtime = current_mtime

            return queue_saturated or self.last_position < current_size
        except Exception:
            return False


class NullParser:
    """Benchmark parser stub that avoids parser hot-path noise."""

    def parse_line(self, line: str) -> None:
        return None


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Benchmark monitor poll-loop overhead.")
    parser.add_argument("--iterations", type=int, default=9)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--polls", type=int, default=5000)
    return parser.parse_args()


def _build_temp_dir() -> Path:
    bench_root = REPO_ROOT / ".bench_tmp"
    bench_root.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="monitor_poll_", dir=bench_root))


def _prepare_logs(temp_dir: Path) -> tuple[Path, Path]:
    log1 = temp_dir / "nwclientLog1.txt"
    log2 = temp_dir / "nwclientLog2.txt"
    log3 = temp_dir / "nwclientLog3.txt"
    log4 = temp_dir / "nwclientLog4.txt"
    log1.write_text("seed line\n" * 4, encoding="utf-8")
    log2.write_text("older line\n" * 2, encoding="utf-8")
    log3.write_text("older line\n", encoding="utf-8")
    log4.write_text("", encoding="utf-8")
    return log1, log2


def _run_idle_known_file(monitor_cls: type[LogDirectoryMonitor] | type[LegacyLogDirectoryMonitor], polls: int) -> float:
    temp_dir = _build_temp_dir()
    try:
        _prepare_logs(temp_dir)
        monitor = monitor_cls(str(temp_dir))
        monitor.start_monitoring()
        parser = NullParser()
        data_queue: queue.Queue = queue.Queue()

        started = perf_counter()
        for _ in range(polls):
            monitor.read_new_lines(parser, data_queue, debug_enabled=False, max_lines_per_poll=1)
        return perf_counter() - started
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _run_tail_one_line(monitor_cls: type[LogDirectoryMonitor] | type[LegacyLogDirectoryMonitor], polls: int) -> float:
    temp_dir = _build_temp_dir()
    try:
        log1, _ = _prepare_logs(temp_dir)
        tail_line = "[CHAT WINDOW TEXT] [Thu Jan 09 14:30:00] Benchmark tail line\n"
        with log1.open("a", encoding="utf-8") as handle:
            handle.write(tail_line)

        monitor = monitor_cls(str(temp_dir))
        monitor.start_monitoring()
        line_bytes = len(tail_line.encode("utf-8"))
        parser = NullParser()
        data_queue: queue.Queue = queue.Queue()

        started = perf_counter()
        for _ in range(polls):
            monitor.last_position -= line_bytes
            monitor.read_new_lines(parser, data_queue, debug_enabled=False, max_lines_per_poll=1)
        return perf_counter() - started
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _measure_scenario(
    label: str,
    runner,
    monitor_cls: type[LogDirectoryMonitor] | type[LegacyLogDirectoryMonitor],
    iterations: int,
    warmups: int,
    polls: int,
) -> dict[str, float | str]:
    for _ in range(warmups):
        runner(monitor_cls, polls)

    timings = [runner(monitor_cls, polls) for _ in range(iterations)]
    median_s = float(statistics.median(timings))
    return {
        "scenario": label,
        "monitor": "current" if monitor_cls is LogDirectoryMonitor else "legacy",
        "median_s": median_s,
        "us_per_poll": (median_s / polls) * 1_000_000,
        "polls_per_s": polls / median_s if median_s > 0 else 0.0,
    }


def main() -> None:
    """Run poll-loop comparisons for current and legacy monitor behavior."""
    args = parse_args()
    scenarios = (
        ("idle_known_file", _run_idle_known_file),
        ("tail_one_line", _run_tail_one_line),
    )

    rows: list[dict[str, float | str]] = []
    for scenario_name, runner in scenarios:
        rows.append(_measure_scenario(
            scenario_name,
            runner,
            LegacyLogDirectoryMonitor,
            args.iterations,
            args.warmups,
            args.polls,
        ))
        rows.append(_measure_scenario(
            scenario_name,
            runner,
            LogDirectoryMonitor,
            args.iterations,
            args.warmups,
            args.polls,
        ))

    by_scenario: dict[str, dict[str, dict[str, float | str]]] = {}
    for row in rows:
        by_scenario.setdefault(str(row["scenario"]), {})[str(row["monitor"])] = row

    headers = ("scenario", "legacy_us_per_poll", "current_us_per_poll", "speedup_x", "poll_reduction_pct")
    widths = {header: len(header) for header in headers}
    formatted_rows: list[dict[str, str]] = []
    for scenario_name in (name for name, _ in scenarios):
        legacy = by_scenario[scenario_name]["legacy"]
        current = by_scenario[scenario_name]["current"]
        legacy_us = float(legacy["us_per_poll"])
        current_us = float(current["us_per_poll"])
        speedup = legacy_us / current_us if current_us > 0 else 0.0
        reduction_pct = ((legacy_us - current_us) / legacy_us * 100.0) if legacy_us > 0 else 0.0
        formatted = {
            "scenario": scenario_name,
            "legacy_us_per_poll": f"{legacy_us:.2f}",
            "current_us_per_poll": f"{current_us:.2f}",
            "speedup_x": f"{speedup:.2f}",
            "poll_reduction_pct": f"{reduction_pct:.1f}%",
        }
        formatted_rows.append(formatted)
        for header, value in formatted.items():
            widths[header] = max(widths[header], len(value))

    print("Monitor poll-loop benchmark")
    print(
        f"Iterations: {args.iterations} measured, {args.warmups} warmup, {args.polls} polls per run"
    )
    print()
    print(" ".join(header.ljust(widths[header]) for header in headers))
    print(" ".join("-" * widths[header] for header in headers))
    for row in formatted_rows:
        print(" ".join(row[header].ljust(widths[header]) for header in headers))


if __name__ == "__main__":
    main()
