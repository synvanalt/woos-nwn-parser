"""Unit tests for import-controller workflow and related app callbacks."""

from __future__ import annotations

import queue
import threading
from collections import deque
from datetime import datetime
from unittest.mock import Mock

import app.ui.controllers.import_controller as import_module
import app.ui.main_window as main_window_module
from app.models import DamageMutation, SaveMutation
from app.parsed_events import DeathCharacterIdentifiedEvent, DeathSnippetEvent
from app.parser import LogParser
from app.ui.controllers.import_controller import ImportController
from app.ui.main_window import WoosNwnParserApp


class _FakeImportToplevel:
    def __init__(self, parent) -> None:
        self.parent = parent
        self._progressbar = None
        self.protocol_calls = {}
        self.attributes_calls = []

    def withdraw(self) -> None:
        return None

    def configure(self, **_kwargs) -> None:
        return None

    def title(self, _value: str) -> None:
        return None

    def resizable(self, _width: bool, _height: bool) -> None:
        return None

    def transient(self, _parent) -> None:
        return None

    def protocol(self, name: str, callback) -> None:
        self.protocol_calls[name] = callback

    def attributes(self, *args) -> None:
        self.attributes_calls.append(args)

    def update_idletasks(self) -> None:
        return None

    def deiconify(self) -> None:
        return None

    def lift(self) -> None:
        return None

    def grab_set(self) -> None:
        return None

    def grab_release(self) -> None:
        return None

    def destroy(self) -> None:
        return None

    def after(self, _ms: int, callback) -> None:
        callback()

    def after_idle(self, callback) -> None:
        callback()


class _FakeWidget:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pack_calls = []
        self.started_with = None
        self.__class__.instances.append(self)

    def pack(self, *args, **kwargs) -> None:
        self.pack_calls.append((args, kwargs))

    def start(self, interval: int) -> None:
        self.started_with = interval

    def stop(self) -> None:
        return None


def _make_controller() -> ImportController:
    return ImportController(
        root=Mock(after=Mock(return_value="poll-next"), after_cancel=Mock()),
        parser=LogParser(parse_immunity=True),
        data_store=Mock(apply_mutations=Mock()),
        dps_panel=Mock(refresh=Mock()),
        death_snippet_panel=Mock(add_death_events=Mock()),
        pause_monitoring=Mock(),
        refresh_targets=Mock(),
        set_controls_busy=Mock(),
        log_debug=Mock(),
        get_window_icon_path=lambda: None,
        center_window_on_parent=Mock(),
        apply_modal_icon=Mock(),
        on_character_identified=Mock(),
        import_apply_frame_budget_ms=6.0,
        import_apply_mutation_batch_size=384,
    )


def _make_app_shell() -> WoosNwnParserApp:
    app = WoosNwnParserApp.__new__(WoosNwnParserApp)
    app.parser = LogParser(parse_immunity=True)
    app.death_snippet_panel = Mock()
    app.dps_panel = Mock()
    app.dps_query_service = Mock()
    app.settings_controller = Mock()
    return app


def _patch_perf_counter(monkeypatch, values: list[float]) -> None:
    ticks = iter(values)
    monkeypatch.setattr(import_module, "perf_counter", lambda: next(ticks))


class TestImportController:
    def test_cancelled_file_selection_noops(self, monkeypatch) -> None:
        controller = _make_controller()
        monkeypatch.setattr(import_module.filedialog, "askopenfilenames", lambda **kwargs: ())

        controller.start_from_dialog(is_monitoring=False)

        assert controller.is_importing is False
        controller.pause_monitoring.assert_not_called()
        controller.set_controls_busy.assert_not_called()

    def test_import_pauses_monitoring_and_sorts_files(self, monkeypatch) -> None:
        controller = _make_controller()
        controller.show_modal = Mock()
        controller.start_worker = Mock()
        controller.poll_progress = Mock()
        monkeypatch.setattr(
            import_module.filedialog,
            "askopenfilenames",
            lambda **kwargs: ("/tmp/zeta.txt", "/tmp/alpha.txt"),
        )

        controller.start_from_dialog(is_monitoring=True)

        assert controller.is_importing is True
        assert controller.monitoring_was_active_before_import is True
        controller.pause_monitoring.assert_called_once_with()
        controller.set_controls_busy.assert_called_once_with(True)
        controller.show_modal.assert_called_once_with()
        controller.poll_progress.assert_called_once_with()
        selected_files = controller.start_worker.call_args.args[0]
        assert [path.name for path in selected_files] == ["alpha.txt", "zeta.txt"]

    def test_abort_sets_event_and_disables_button(self) -> None:
        controller = _make_controller()
        controller.is_importing = True
        controller.import_abort_button = Mock()
        controller.import_status_text = Mock()

        controller.abort()

        assert controller.import_abort_event.is_set() is True
        controller.import_abort_button.config.assert_called_once_with(state=import_module.tk.DISABLED)
        controller.import_status_text.set.assert_called_once_with("Aborting...")

    def test_show_import_modal_places_abort_button_in_bottom_actions_row(self, monkeypatch) -> None:
        controller = _make_controller()

        class FakeFrame(_FakeWidget):
            instances = []

        class FakeLabel(_FakeWidget):
            instances = []

        class FakeProgressbar(_FakeWidget):
            instances = []

        class FakeButton(_FakeWidget):
            instances = []

        monkeypatch.setattr(import_module.tk, "Toplevel", _FakeImportToplevel)
        monkeypatch.setattr(import_module.ttk, "Frame", FakeFrame)
        monkeypatch.setattr(import_module.ttk, "Label", FakeLabel)
        monkeypatch.setattr(import_module.ttk, "Progressbar", FakeProgressbar)
        monkeypatch.setattr(import_module.ttk, "Button", FakeButton)
        monkeypatch.setattr(import_module, "apply_dark_title_bar", Mock())
        monkeypatch.setattr(import_module.tk, "StringVar", lambda value=None: Mock(value=value))

        controller.show_modal()

        assert len(FakeFrame.instances) == 2
        assert FakeFrame.instances[1].pack_calls == [((), {"side": "bottom", "fill": "x"})]
        assert FakeButton.instances[0].pack_calls == [((), {"anchor": "e"})]
        assert FakeProgressbar.instances[0].started_with == 8

    def test_finalize_import_resets_ui_and_refreshes(self) -> None:
        controller = _make_controller()
        controller.import_poll_job = "poll-id"
        controller.is_importing = True
        progress = Mock(stop=Mock())
        modal = _FakeImportToplevel(None)
        modal._progressbar = progress
        modal.grab_release = Mock()
        modal.destroy = Mock()
        controller.import_modal = modal
        controller._import_status = {"total_files": 2, "errors": [], "aborted": False}

        controller.finalize()

        controller.root.after_cancel.assert_called_once_with("poll-id")
        controller.set_controls_busy.assert_called_once_with(False)
        progress.stop.assert_called_once_with()
        modal.grab_release.assert_called_once_with()
        modal.destroy.assert_called_once_with()
        controller.refresh_targets.assert_called_once_with()
        controller.dps_panel.refresh.assert_called_once_with()
        assert controller.is_importing is False

    def test_file_counter_updates_immediately_on_file_completed_event(self) -> None:
        controller = _make_controller()
        controller.import_result_queue = queue.Queue()
        controller._import_status = {
            "files_completed": 0,
            "total_files": 2,
            "current_file": "alpha.txt",
            "errors": [],
            "aborted": False,
            "success": False,
            "worker_done": False,
        }
        controller.import_result_queue.put({"event": "file_completed", "index": 1, "file_name": "alpha.txt"})

        controller.drain_events()

        assert controller._import_status["files_completed"] == 1
        assert len(controller._pending_file_payloads) == 0
        controller.root.after.assert_not_called()

    def test_apply_pending_payloads_uses_event_api_for_death_snippets(self) -> None:
        controller = _make_controller()
        controller._is_applying_payload = True
        controller._pending_file_payloads.append(
            {
                "mutations": [],
                "death_snippets": [
                    {
                        "timestamp": None,
                        "killer": "HYDROXIS",
                        "target": "Woo Wildrock",
                        "lines": ["line-1", "line-2"],
                    }
                ],
                "death_character_identified": [],
                "index": 1,
                "mutation_idx": 0,
            }
        )

        controller.apply_pending_payloads_incremental()

        controller.death_snippet_panel.add_death_events.assert_called_once()
        emitted = controller.death_snippet_panel.add_death_events.call_args.args[0]
        assert len(emitted) == 1
        assert isinstance(emitted[0], DeathSnippetEvent)

    def test_apply_pending_payloads_forwards_death_character_identified_events(self) -> None:
        controller = _make_controller()
        controller._is_applying_payload = True
        controller._pending_file_payloads.append(
            {
                "mutations": [],
                "death_snippets": [],
                "death_character_identified": [{"character_name": "Woo Wildrock"}],
                "index": 1,
                "mutation_idx": 0,
            }
        )

        controller.apply_pending_payloads_incremental()

        emitted = controller.on_character_identified.call_args.args[0]
        assert isinstance(emitted, DeathCharacterIdentifiedEvent)
        assert emitted.character_name == "Woo Wildrock"

    def test_apply_pending_payloads_incremental_spans_ticks_and_drains(self, monkeypatch) -> None:
        controller = _make_controller()
        controller.import_apply_mutation_batch_size = 1
        controller._is_applying_payload = True
        controller._pending_file_payloads.append(
            {
                "mutations": [
                    DamageMutation(
                        target="Goblin",
                        total_damage=10,
                        attacker="Orc",
                        timestamp=1.0,
                        count_for_dps=True,
                        damage_types={"slashing": 10},
                    )
                ],
                "death_snippets": [],
                "death_character_identified": [],
                "index": 1,
                "mutation_idx": 0,
            }
        )

        _patch_perf_counter(monkeypatch, [0.0, 0.0, 0.007])
        controller.apply_pending_payloads_incremental()

        assert len(controller._pending_file_payloads) == 1
        assert controller._pending_file_payloads[0]["mutation_idx"] == 1
        assert controller._is_applying_payload is True
        controller.root.after.assert_called_once_with(1, controller.apply_pending_payloads_incremental)
        controller.data_store.apply_mutations.assert_called_once()

        _patch_perf_counter(monkeypatch, [1.0] * 20)
        controller.apply_pending_payloads_incremental()

        assert len(controller._pending_file_payloads) == 0
        assert controller._is_applying_payload is False

    def test_apply_pending_payloads_batches_multiple_mutations_per_apply_call(self, monkeypatch) -> None:
        controller = _make_controller()
        controller.import_apply_mutation_batch_size = 2
        controller._is_applying_payload = True
        mutations = [
            SaveMutation(target="Goblin", save_key="fort", bonus=4),
            SaveMutation(target="Goblin", save_key="reflex", bonus=5),
            SaveMutation(target="Goblin", save_key="will", bonus=6),
        ]
        controller._pending_file_payloads.append(
            {
                "mutations": mutations,
                "death_snippets": [],
                "death_character_identified": [],
                "index": 1,
                "mutation_idx": 0,
            }
        )

        _patch_perf_counter(monkeypatch, [0.0] * 20)
        controller.apply_pending_payloads_incremental()

        assert controller.data_store.apply_mutations.call_count == 2
        assert controller.data_store.apply_mutations.call_args_list[0].args[0] == mutations[:2]
        assert controller.data_store.apply_mutations.call_args_list[1].args[0] == mutations[2:]

    def test_poll_import_progress_waits_for_streaming_apply_before_finalize(self, monkeypatch) -> None:
        controller = _make_controller()
        controller.is_importing = True
        controller.import_result_queue = queue.Queue()
        controller.finalize = Mock()
        controller._import_status = {
            "files_completed": 0,
            "total_files": 1,
            "current_file": "alpha.txt",
            "errors": [],
            "aborted": False,
            "success": False,
            "worker_done": False,
        }
        controller.import_result_queue.put(
            {
                "event": "ops_chunk",
                "index": 1,
                "ops": {
                    "mutations": [
                        DamageMutation(
                            target="Goblin",
                            total_damage=10,
                            attacker="Orc",
                            timestamp=1.0,
                            count_for_dps=True,
                            damage_types={"slashing": 10},
                        )
                    ]
                },
            }
        )
        controller.import_result_queue.put({"event": "file_completed", "index": 1, "file_name": "alpha.txt"})
        controller.import_result_queue.put({"event": "done"})

        controller.poll_progress()

        assert controller._is_applying_payload is True
        controller.finalize.assert_not_called()

        _patch_perf_counter(monkeypatch, [0.0] * 30)
        controller.apply_pending_payloads_incremental()
        controller.poll_progress()

        controller.finalize.assert_called_once_with()

    def test_start_import_worker_passes_death_settings_to_worker(self, monkeypatch) -> None:
        controller = _make_controller()
        controller.parser = Mock(
            parse_immunity=True,
            death_character_name="Woo Wildrock",
            death_fallback_line="Custom fallback",
        )

        class FakeProcess:
            def __init__(self, target, args, daemon) -> None:
                self.target = target
                self.args = args
                self.daemon = daemon
                self.started = False

            def start(self) -> None:
                self.started = True

        class FakeContext:
            def __init__(self) -> None:
                self.process = None
                self.event = object()
                self.queue = object()

            def Event(self):
                return self.event

            def Queue(self, maxsize=0):
                self.queue_maxsize = maxsize
                return self.queue

            def Process(self, target, args, daemon):
                self.process = FakeProcess(target=target, args=args, daemon=daemon)
                return self.process

        fake_ctx = FakeContext()
        monkeypatch.setattr(import_module.mp, "get_context", lambda _name: fake_ctx)

        controller.start_worker([import_module.Path("alpha.txt")])

        assert controller.import_abort_flag is fake_ctx.event
        assert controller.import_result_queue is fake_ctx.queue
        assert controller.import_process is fake_ctx.process
        assert fake_ctx.process.started is True
        assert fake_ctx.process.args[4] == "Woo Wildrock"
        assert fake_ctx.process.args[5] == "Custom fallback"


class TestMainWindowCallbacks:
    def test_on_death_snippet_forwards_event_to_panel(self) -> None:
        app = _make_app_shell()
        event = DeathSnippetEvent(
            target="Woo Wildrock",
            killer="HYDROXIS",
            lines=["line-1", "line-2"],
            timestamp=datetime.min,
            line_number=None,
        )

        app._on_death_snippet(event)

        app.death_snippet_panel.add_death_event.assert_called_once_with(event)

    def test_on_death_character_identified_sets_panel_character(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel.get_character_name.return_value = ""

        app._on_death_character_identified(
            DeathCharacterIdentifiedEvent(
                character_name="Woo Wildrock",
                timestamp=datetime.min,
                line_number=None,
            )
        )

        app.death_snippet_panel.set_character_name.assert_called_once_with("Woo Wildrock")

    def test_on_death_character_identified_does_not_overwrite_existing_name(self) -> None:
        app = _make_app_shell()
        app.death_snippet_panel.get_character_name.return_value = "Existing Name"

        app._on_death_character_identified(
            DeathCharacterIdentifiedEvent(
                character_name="Woo Wildrock",
                timestamp=datetime.min,
                line_number=None,
            )
        )

        app.death_snippet_panel.set_character_name.assert_not_called()

    def test_on_death_character_identified_ignores_empty_name(self) -> None:
        app = _make_app_shell()

        app._on_death_character_identified(
            DeathCharacterIdentifiedEvent(
                character_name="   ",
                timestamp=datetime.min,
                line_number=None,
            )
        )

        app.death_snippet_panel.get_character_name.assert_not_called()

    def test_identity_and_fallback_callbacks_update_parser(self) -> None:
        app = _make_app_shell()
        app.parser = Mock()
        app._schedule_session_settings_save = Mock()

        app._on_death_character_name_changed("Woo Wildrock")
        app._on_death_fallback_line_changed("Your God refuses to hear your prayers!")

        app.parser.set_death_character_name.assert_called_once_with("Woo Wildrock")
        app.parser.set_death_fallback_line.assert_called_once_with("Your God refuses to hear your prayers!")
        app._schedule_session_settings_save.assert_called_once_with()

    def test_parse_immunity_callback_updates_parser_and_schedules_save(self) -> None:
        app = _make_app_shell()
        app.parser = Mock()
        app._schedule_session_settings_save = Mock()

        app._on_parse_immunity_changed(False)

        assert app.parser.parse_immunity is False
        app._schedule_session_settings_save.assert_called_once_with()

    def test_build_session_settings_delegates_to_controller(self) -> None:
        app = _make_app_shell()
        app.settings_controller.build_settings.return_value = "settings"

        assert app._build_session_settings() == "settings"
        app.settings_controller.build_settings.assert_called_once_with()

    def test_schedule_session_settings_save_delegates_to_controller(self) -> None:
        app = _make_app_shell()

        app._schedule_session_settings_save()

        app.settings_controller.schedule_save.assert_called_once_with()

    def test_flush_pending_session_settings_save_updates_cached_settings(self) -> None:
        app = _make_app_shell()
        app.settings_controller.settings = "saved-settings"

        app._flush_pending_session_settings_save()

        app.settings_controller.flush_pending_save.assert_called_once_with()
        assert app._settings == "saved-settings"
