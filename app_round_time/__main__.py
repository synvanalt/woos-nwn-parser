"""CLI entry point for round time measurement."""

from __future__ import annotations

import argparse
import time
import os
from pathlib import Path

from .log_reader import LogReader
from .parser import LogParser
from .round_timer import RoundTimer
from .watcher import DirectoryWatcher

# python -m app_round_time --log-dir "C:\Users\Synvan\Documents\Neverwinter Nights\logs" --character "Woo Windraven" --apr 6

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NWN round time measurement utility")
    parser.add_argument("--log-dir", required=True, help="Directory containing nwclientLog*.txt")
    parser.add_argument("--character", required=True, help="Character name to track")
    parser.add_argument("--apr", required=True, type=int, help="Attacks per round")
    parser.add_argument("--include-aoo", action="store_true", help="Include Attack Of Opportunity lines")
    parser.add_argument("--print-every", type=int, default=1, help="Print stats every N rounds")
    parser.add_argument(
        "--round-mode",
        choices=("next_start", "last_attack"),
        default="next_start",
        help="Round duration mode: next_start (start-to-start) or last_attack (first-to-last)",
    )
    parser.add_argument("--high-priority", action="store_true", default=True, help="Set watcher thread to high priority")
    parser.add_argument("--no-high-priority", action="store_true", help="Disable high priority for watcher thread")
    parser.add_argument("--affinity-cpu", type=int, default=None, help="Pin watcher thread to CPU core index")
    parser.add_argument("--lag-stats", action="store_true", default=True, help="Enable lag statistics")
    parser.add_argument("--no-lag-stats", action="store_true", help="Disable lag statistics")
    parser.add_argument("--debug-watch", action="store_true", help="Print watcher and read diagnostics")
    parser.add_argument("--debug-parse", action="store_true", help="Print parsing diagnostics for attack lines")
    parser.add_argument("--debug-parse-lines", type=int, default=50, help="Limit for debug parse prints")
    parser.add_argument("--no-normalize-name", action="store_true", help="Disable name normalization (trim/collapse spaces)")
    parser.add_argument(
        "--min-round-seconds",
        type=float,
        default=5.0,
        help="Ignore round durations shorter than this threshold (0 disables)",
    )
    parser.add_argument(
        "--burst-ms",
        type=int,
        default=200,
        help="After a change event, keep reading for this many ms to catch streamed lines",
    )
    parser.add_argument(
        "--burst-sleep-ms",
        type=int,
        default=5,
        help="Sleep duration between burst reads when no new lines are found",
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=0,
        help="Optional fallback polling interval in ms (0 disables polling)",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        print(f"Log directory does not exist: {log_dir}")
        return 1

    exclude_aoo = not args.include_aoo
    high_priority = args.high_priority and not args.no_high_priority
    lag_stats = args.lag_stats and not args.no_lag_stats
    affinity_cpu = args.affinity_cpu
    cpu_count = os.cpu_count() or 0
    if affinity_cpu is not None and cpu_count and (affinity_cpu < 0 or affinity_cpu >= cpu_count):
        print(f"Warning: --affinity-cpu {affinity_cpu} is out of range (0-{cpu_count - 1}). Ignoring affinity.", flush=True)
        affinity_cpu = None

    parser = LogParser()
    reader = LogReader(str(log_dir))
    reader.initialize(start_at_end=True)

    timer = RoundTimer(
        character_name=args.character,
        attacks_per_round=args.apr,
        exclude_aoo=exclude_aoo,
        match_mode="exact",
        print_every=args.print_every,
        lag_stats=lag_stats,
        round_mode=args.round_mode,
        debug=args.debug_parse,
        normalize_name=not args.no_normalize_name,
        min_round_seconds=args.min_round_seconds,
    )

    debug_parse_count = 0

    def on_line(raw_line: str, wall_time_ns: int, perf_ns: int) -> None:
        nonlocal debug_parse_count
        event = parser.parse_line(raw_line)
        if args.debug_parse and debug_parse_count < args.debug_parse_lines:
            if event:
                print(f"Parsed attack: {event.attacker} -> {event.target} ({event.outcome})", flush=True)
                debug_parse_count += 1
            elif "attacks" in raw_line.lower():
                print(f"Unparsed attack line: {raw_line.strip()}", flush=True)
                debug_parse_count += 1
        if not event:
            return
        output = timer.process_attack(event, raw_line, wall_time_ns, perf_ns)
        if output:
            print(output, flush=True)

    def on_change() -> None:
        total = 0
        count = reader.read_new_lines(on_line)
        total += count
        if args.burst_ms and args.burst_ms > 0:
            burst_deadline = time.time() + (args.burst_ms / 1000.0)
            while time.time() < burst_deadline:
                count = reader.read_new_lines(on_line)
                if count:
                    total += count
                    continue
                time.sleep(max(0.0, args.burst_sleep_ms / 1000.0))
        if args.debug_watch:
            print(f"Watcher event: read {total} line(s).", flush=True)

    watcher = DirectoryWatcher(
        str(log_dir),
        on_change=on_change,
        high_priority=high_priority,
        affinity_cpu=affinity_cpu,
        debug=args.debug_watch,
    )

    print("Round time measurement started. Waiting for attacks...", flush=True)
    initial_count = reader.read_new_lines(on_line)
    if args.debug_watch:
        active = reader.get_active_log_file()
        if active and active.exists():
            size = active.stat().st_size
            print(f"Active log: {active.name} ({size} bytes)", flush=True)
        else:
            print("Active log: not found (no nwclientLog1-4.txt?)", flush=True)
        print(f"Initial read: {initial_count} line(s).", flush=True)
    watcher.start()

    try:
        while True:
            if args.poll_ms and args.poll_ms > 0:
                reader.read_new_lines(on_line)
                time.sleep(args.poll_ms / 1000.0)
            else:
                time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...", flush=True)
    finally:
        watcher.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
