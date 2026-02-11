"""Round time measurement logic and reporting."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .models import AttackEvent
from .stats import mean_std


class RoundTimer:
    def __init__(
        self,
        character_name: str,
        attacks_per_round: int,
        exclude_aoo: bool = True,
        match_mode: str = "exact",
        print_every: int = 1,
        lag_stats: bool = True,
        round_mode: str = "next_start",
        debug: bool = False,
        normalize_name: bool = True,
        min_round_seconds: float = 0.0,
    ) -> None:
        self.normalize_name = normalize_name
        self.character_name = self._normalize_name(character_name) if normalize_name else character_name
        self.attacks_per_round = attacks_per_round
        self.exclude_aoo = exclude_aoo
        self.match_mode = match_mode
        self.print_every = max(1, int(print_every))
        self.lag_stats = lag_stats
        self.round_mode = round_mode
        self.debug = debug
        self.min_round_seconds = float(min_round_seconds)

        self.current_count = 0
        self.rounds_completed = 0
        self.round_start_log_ts: Optional[datetime] = None
        self.round_start_perf_ns: Optional[int] = None
        self.prev_round_start_log_ts: Optional[datetime] = None
        self.prev_round_start_perf_ns: Optional[int] = None
        self.prev_round_ready: bool = False

        self.log_samples: List[float] = []
        self.wall_samples: List[float] = []
        self.lag_samples: List[float] = []
        self.last_log_seconds: Optional[float] = None
        self.last_wall_seconds: Optional[float] = None

    def _matches_character(self, attacker: str) -> bool:
        name = self._normalize_name(attacker) if self.normalize_name else attacker
        if self.match_mode == "exact":
            return name == self.character_name
        return name == self.character_name

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.strip().split())

    def process_attack(
        self,
        event: AttackEvent,
        raw_line: str,
        wall_time_ns: int,
        perf_ns: int,
    ) -> Optional[str]:
        if not self._matches_character(event.attacker):
            return None

        if self.exclude_aoo and "attack of opportunity" in raw_line.lower():
            return None

        if self.lag_stats and event.log_timestamp:
            try:
                log_epoch = event.log_timestamp.timestamp()
                wall_epoch = wall_time_ns / 1_000_000_000
                self.lag_samples.append(wall_epoch - log_epoch)
            except Exception:
                pass

        if self.current_count == 0:
            if self.round_mode == "next_start" and self.prev_round_ready:
                log_delta = None
                if self.prev_round_start_log_ts and event.log_timestamp:
                    log_delta = (event.log_timestamp - self.prev_round_start_log_ts).total_seconds()
                wall_delta = None
                if self.prev_round_start_perf_ns is not None:
                    wall_delta = (perf_ns - self.prev_round_start_perf_ns) / 1_000_000_000

                delta_for_gate = log_delta if log_delta is not None else wall_delta
                if self.min_round_seconds > 0 and delta_for_gate is not None:
                    if delta_for_gate < self.min_round_seconds:
                        if self.debug:
                            print(
                                f"Ignoring short round ({delta_for_gate:.2f}s < {self.min_round_seconds:.2f}s).",
                                flush=True,
                            )
                        self.prev_round_ready = False
                        self.round_start_log_ts = event.log_timestamp
                        self.round_start_perf_ns = perf_ns
                        self.current_count = 1
                        if self.debug:
                            print(f"Round count: {self.current_count}/{self.attacks_per_round}", flush=True)
                        return None

                if log_delta is not None:
                    self.log_samples.append(log_delta)
                    self.last_log_seconds = log_delta
                if wall_delta is not None:
                    self.wall_samples.append(wall_delta)
                    self.last_wall_seconds = wall_delta

                self.rounds_completed += 1

                if self.rounds_completed % self.print_every == 0:
                    log_mean, log_std, log_n = mean_std(self.log_samples)
                    wall_mean, wall_std, wall_n = mean_std(self.wall_samples)
                    last_log = self.last_log_seconds if self.last_log_seconds is not None else 0.0
                    last_wall = self.last_wall_seconds if self.last_wall_seconds is not None else 0.0
                    output = (
                        f"Rounds: {self.rounds_completed} | "
                        f"(LogTime/WallTime) Last: {last_log:.2f}s/{last_wall:.2f}s | "
                        f"Avg: {log_mean:.2f}s/{wall_mean:.2f}s | "
                        f"STD: {log_std:.2f}s/{wall_std:.2f}s"
                    )
                    if self.lag_stats:
                        lag_mean, lag_std, lag_n = mean_std(self.lag_samples)
                        output += f" | Lag: {lag_mean:.2f}±{lag_std:.2f}s (n={lag_n})"
                else:
                    output = None
            else:
                output = None

            self.prev_round_ready = False
            self.round_start_log_ts = event.log_timestamp
            self.round_start_perf_ns = perf_ns
            self.current_count = 1
            if self.debug:
                print(f"Round count: {self.current_count}/{self.attacks_per_round}", flush=True)
            return output
        self.current_count += 1
        if self.debug:
            print(f"Round count: {self.current_count}/{self.attacks_per_round}", flush=True)

        if self.current_count < self.attacks_per_round:
            return None

        if self.round_mode == "next_start":
            self.prev_round_ready = True
            self.prev_round_start_log_ts = self.round_start_log_ts
            self.prev_round_start_perf_ns = self.round_start_perf_ns
            self.current_count = 0
            self.round_start_log_ts = None
            self.round_start_perf_ns = None
            if self.debug:
                print("Round complete; waiting for next round start.", flush=True)
            return None

        log_delta = None
        if self.round_start_log_ts and event.log_timestamp:
            log_delta = (event.log_timestamp - self.round_start_log_ts).total_seconds()

        wall_delta = None
        if self.round_start_perf_ns is not None:
            wall_delta = (perf_ns - self.round_start_perf_ns) / 1_000_000_000

        if log_delta is not None:
            self.log_samples.append(log_delta)
            self.last_log_seconds = log_delta
        if wall_delta is not None:
            self.wall_samples.append(wall_delta)
            self.last_wall_seconds = wall_delta

        self.current_count = 0
        self.round_start_log_ts = None
        self.round_start_perf_ns = None

        self.rounds_completed += 1
        if self.rounds_completed % self.print_every != 0:
            return None

        log_mean, log_std, log_n = mean_std(self.log_samples)
        wall_mean, wall_std, wall_n = mean_std(self.wall_samples)

        last_log = self.last_log_seconds if self.last_log_seconds is not None else 0.0
        last_wall = self.last_wall_seconds if self.last_wall_seconds is not None else 0.0
        output = (
            f"Rounds: {self.rounds_completed} | "
            f"(LogTime/WallTime) Last: {last_log:.2f}s/{last_wall:.2f}s | "
            f"Avg: {log_mean:.2f}s/{wall_mean:.2f}s | "
            f"STD: {log_std:.2f}s/{wall_std:.2f}s"
        )

        if self.lag_stats:
            lag_mean, lag_std, lag_n = mean_std(self.lag_samples)
            output += f" | Lag: {lag_mean:.2f}±{lag_std:.2f}s (n={lag_n})"

        return output
