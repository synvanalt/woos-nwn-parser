"""Unit tests for RefreshCoordinator."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.services.queue_processor import QueueDrainResult
from app.ui.controllers.refresh_coordinator import RefreshCoordinator


def test_handle_queue_result_marks_dirty_and_schedules_once() -> None:
    root = Mock()
    root.after = Mock(return_value="refresh-job")
    coordinator = RefreshCoordinator(
        root=root,
        dps_panel=Mock(),
        stats_panel=Mock(),
        immunity_panel=SimpleNamespace(target_combo=SimpleNamespace(get=lambda: "")),
        refresh_targets=Mock(),
        on_death_snippet=Mock(),
        on_character_identified=Mock(),
    )

    coordinator.handle_queue_result(
        QueueDrainResult(
            dps_updated=True,
            targets_to_refresh={"Goblin"},
        )
    )

    assert coordinator.dps_dirty is True
    assert coordinator.targets_dirty is True
    root.after.assert_called_once_with(180, coordinator.run)


def test_run_refreshes_targets_then_dps_then_selected_immunity() -> None:
    call_order: list[str] = []
    root = Mock()
    root.after = Mock(return_value="refresh-job")
    immunity_panel = Mock()
    immunity_panel.target_combo.get.return_value = "Goblin"
    immunity_panel.refresh_target_details.side_effect = lambda target: call_order.append(f"immunity:{target}")
    dps_panel = Mock()
    dps_panel.refresh.side_effect = lambda: call_order.append("dps")
    refresh_targets = Mock(side_effect=lambda: call_order.append("targets"))

    coordinator = RefreshCoordinator(
        root=root,
        dps_panel=dps_panel,
        stats_panel=Mock(),
        immunity_panel=immunity_panel,
        refresh_targets=refresh_targets,
        on_death_snippet=Mock(),
        on_character_identified=Mock(),
    )
    coordinator._targets_dirty = True
    coordinator._dps_dirty = True
    coordinator._immunity_dirty_targets.add("Goblin")

    coordinator.run()

    assert call_order == ["targets", "dps", "immunity:Goblin"]
