"""Backward-compatible import for the DPS query service."""

from .queries.dps_query_service import DpsQueryService


class DPSCalculationService(DpsQueryService):
    """Compatibility wrapper around the DPS query service."""

    pass


