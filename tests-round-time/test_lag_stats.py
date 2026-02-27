from datetime import datetime

from app_round_time.models import AttackEvent
from app_round_time.round_timer import RoundTimer


def test_lag_stats_accumulates():
    timer = RoundTimer("Toon", attacks_per_round=2, exclude_aoo=True, print_every=1, lag_stats=True)

    ts1 = datetime(2026, 1, 1, 12, 0, 0)
    e1 = AttackEvent(attacker="Toon", target="Goblin", outcome="hit", log_timestamp=ts1)

    timer.process_attack(e1, "Toon attacks Goblin: *hit*", 1_000_000_000, 1_000_000_000)

    assert len(timer.lag_samples) == 1
