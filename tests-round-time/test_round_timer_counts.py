from datetime import datetime

from app_round_time.models import AttackEvent
from app_round_time.round_timer import RoundTimer


def test_round_timer_counts_and_resets():
    timer = RoundTimer("Toon", attacks_per_round=2, exclude_aoo=True, print_every=1, lag_stats=False)

    ts1 = datetime(2026, 1, 1, 12, 0, 0)
    ts2 = datetime(2026, 1, 1, 12, 0, 1)

    e1 = AttackEvent(attacker="Toon", target="Goblin", outcome="hit", log_timestamp=ts1)
    e2 = AttackEvent(attacker="Toon", target="Goblin", outcome="hit", log_timestamp=ts2)

    out1 = timer.process_attack(e1, "Toon attacks Goblin: *hit*", 1_000_000_000, 1_000_000_000)
    assert out1 is None

    out2 = timer.process_attack(e2, "Toon attacks Goblin: *hit*", 2_000_000_000, 2_000_000_000)
    assert out2 is not None
    assert "Samples: 1" in out2
    assert timer.current_count == 0
