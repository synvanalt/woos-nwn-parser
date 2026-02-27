from app_round_time.parser import LogParser


def test_parse_attack_line_basic():
    parser = LogParser()
    line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:48:11] Toon attacks Goblin: *hit* : (12 + 5 = 17)"
    event = parser.parse_line(line)
    assert event is not None
    assert event.attacker == "Toon"
    assert event.target == "Goblin"
    assert event.outcome == "hit"
    assert event.log_timestamp is not None


def test_parse_attack_line_critical():
    parser = LogParser()
    line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:48:12] Toon attacks Orc: *critical hit* : (20 + 6 = 26) : Threat Roll: *hit*"
    event = parser.parse_line(line)
    assert event is not None
    assert event.outcome == "critical hit"


def test_parse_non_attack_line():
    parser = LogParser()
    line = "[CHAT WINDOW TEXT] [Tue Jan 13 19:48:11] Toon damages Orc: 10 (10 Physical)"
    event = parser.parse_line(line)
    assert event is None
