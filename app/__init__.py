"""Woo's NWN Parser public package surface.

The application is primarily wired through ``app.__main__`` and the Tk UI, but a
small set of parser, storage, monitoring, and query types are re-exported here
for tests and external tooling.
"""

__version__ = "1.7.0"
__author__ = "Synvan"

from .constants import DAMAGE_TYPE_PALETTE
from .models import (
    EnemySaves,
    EnemyAC,
    DamageEvent,
    AttackEvent,
)
from .parser import LineParser, ParserSession
from .storage import DataStore
from .monitor import LogDirectoryMonitor
from .services import QueueProcessor
from .services.queries import DpsQueryService, ImmunityQueryService, TargetSummaryQueryService

__all__ = [
    "__version__",
    "DAMAGE_TYPE_PALETTE",
    "EnemySaves",
    "EnemyAC",
    "DamageEvent",
    "AttackEvent",
    "LineParser",
    "ParserSession",
    "DataStore",
    "LogDirectoryMonitor",
    "QueueProcessor",
    "DpsQueryService",
    "ImmunityQueryService",
    "TargetSummaryQueryService",
]

