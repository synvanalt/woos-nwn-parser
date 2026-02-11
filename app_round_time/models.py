"""Data models for the standalone round-time utility."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class AttackEvent:
    attacker: str
    target: str
    outcome: str
    log_timestamp: Optional[datetime]


@dataclass(slots=True)
class RoundSample:
    log_seconds: float
    wall_seconds: float
