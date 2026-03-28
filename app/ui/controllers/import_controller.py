"""Import workflow orchestration for selected log-file parsing."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import multiprocessing as mp
from pathlib import Path
import queue
from threading import Event, Lock
from time import perf_counter
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, ttk

from ...parsed_events import DeathCharacterIdentifiedEvent, DeathSnippetEvent
from ...utils import IMPORT_RESULT_QUEUE_MAXSIZE, import_worker_process
from ..message_dialogs import show_warning_dialog
from ..window_style import apply_dark_title_bar


class ImportController:
    """Own import modal, worker, and incremental payload application state."""

    def __init__(
        self,
        *,
        root: tk.Misc,
        parser,
        data_store,
        dps_panel,
        death_snippet_panel,
        pause_monitoring: Callable[[], None],
        refresh_targets: Callable[[], None],
        set_controls_busy: Callable[[bool], None],
        log_debug: Callable[[str, str], None],
        get_window_icon_path: Callable[[], str | None],
        center_window_on_parent: Callable[[tk.Toplevel, int, int], None],
        apply_modal_icon: Callable[[tk.Toplevel], None],
        on_character_identified: Callable[[DeathCharacterIdentifiedEvent], None],
        import_apply_frame_budget_ms: float,
        import_apply_mutation_batch_size: int,
    ) -> None:
        self.root = root
        self.parser = parser
        self.data_store = data_store
        self.dps_panel = dps_panel
        self.death_snippet_panel = death_snippet_panel
        self.pause_monitoring = pause_monitoring
        self.refresh_targets = refresh_targets
        self.set_controls_busy = set_controls_busy
        self.log_debug = log_debug
        self.get_window_icon_path = get_window_icon_path
        self.center_window_on_parent = center_window_on_parent
        self.apply_modal_icon = apply_modal_icon
        self.on_character_identified = on_character_identified
        self.import_apply_frame_budget_ms = import_apply_frame_budget_ms
        self.import_apply_mutation_batch_size = import_apply_mutation_batch_size

        self.is_importing = False
        self.monitoring_was_active_before_import = False
        self.import_abort_event = Event()
        self.import_process = None
        self.import_abort_flag = None
        self.import_result_queue = None
        self.import_poll_job = None
        self.import_modal: tk.Toplevel | None = None
        self.import_status_text: tk.StringVar | None = None
        self.import_progress_text: tk.StringVar | None = None
        self.import_abort_button = None
        self.import_progressbar = None
        self._import_status_lock = Lock()
        self._import_status: dict[str, Any] = {}
        self._pending_file_payloads = deque()
        self._is_applying_payload = False
        self._last_modal_file = ""
        self._last_modal_files_completed = -1

    @staticmethod
    def death_snippet_from_payload(payload: dict[str, Any]) -> DeathSnippetEvent:
        """Build a typed death-snippet event from import payload data."""
        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, datetime):
            timestamp = datetime.min
        return DeathSnippetEvent(
            target=str(payload.get("target", "")),
            killer=str(payload.get("killer", "")),
            lines=list(payload.get("lines", []) or []),
            timestamp=timestamp,
            line_number=None,
        )

    @staticmethod
    def death_character_identified_from_payload(
        payload: dict[str, Any],
    ) -> DeathCharacterIdentifiedEvent:
        """Build a typed identity event from import payload data."""
        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, datetime):
            timestamp = datetime.min
        return DeathCharacterIdentifiedEvent(
            character_name=str(payload.get("character_name", "")),
            timestamp=timestamp,
            line_number=None,
        )

    def start_from_dialog(self, *, is_monitoring: bool) -> None:
        """Open file picker and start background import if files were chosen."""
        if self.is_importing:
            return
        selected_paths = filedialog.askopenfilenames(
            title="Select one or more NWN log files",
            filetypes=[("Text Files", "*.txt")],
            parent=self.root,
        )
        if not selected_paths:
            return

        selected_files = sorted(
            [Path(path) for path in selected_paths],
            key=lambda path: (path.name.lower(), str(path).lower()),
        )

        self.monitoring_was_active_before_import = bool(is_monitoring)
        if self.monitoring_was_active_before_import:
            self.pause_monitoring()

        self.import_abort_event = Event()
        self.is_importing = True
        self._import_status = {
            "files": selected_files,
            "total_files": len(selected_files),
            "files_completed": 0,
            "current_file": "",
            "errors": [],
            "aborted": False,
            "success": False,
            "worker_done": False,
        }
        self._last_modal_file = ""
        self._last_modal_files_completed = -1
        self._pending_file_payloads.clear()
        self._is_applying_payload = False

        self.set_controls_busy(True)
        self.show_modal()
        self.start_worker(selected_files)
        self.poll_progress()

    def show_modal(self) -> None:
        """Show modal progress UI for background import work."""
        self.import_modal = tk.Toplevel(self.root)
        self.import_modal.withdraw()
        self.import_modal.configure(bg="#1c1c1c")
        self.import_modal.title("Parsing Logs")
        self.import_modal.resizable(False, False)
        self.import_modal.transient(self.root)
        self.center_window_on_parent(self.import_modal, 480, 140)
        self.apply_modal_icon(self.import_modal)
        try:
            apply_dark_title_bar(self.import_modal)
        except Exception:
            pass

        container = ttk.Frame(self.import_modal, padding=14)
        container.pack(fill="both", expand=True)

        self.import_status_text = tk.StringVar(value="Preparing selected files...")
        self.import_progress_text = tk.StringVar(value="0 files completed")
        ttk.Label(container, textvariable=self.import_status_text).pack(anchor="w")
        ttk.Label(container, textvariable=self.import_progress_text).pack(anchor="w", pady=(8, 8))

        progress = ttk.Progressbar(container, mode="indeterminate")
        progress.pack(fill="x")
        progress.start(8)
        self.import_progressbar = progress

        actions = ttk.Frame(container)
        actions.pack(side="bottom", fill="x")

        self.import_abort_button = ttk.Button(actions, text="Abort", command=self.abort)
        self.import_abort_button.pack(anchor="e")
        self.import_modal.protocol("WM_DELETE_WINDOW", self.abort)

        try:
            self.import_modal.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        def reveal_after_ready() -> None:
            if self.import_modal is None:
                return
            self.import_modal.update_idletasks()
            self.import_modal.deiconify()
            self.import_modal.lift()

            def reveal_after_repaints(remaining_repaints: int = 4) -> None:
                if self.import_modal is None:
                    return
                self.import_modal.update_idletasks()
                if remaining_repaints > 0:
                    self.import_modal.after(16, lambda: reveal_after_repaints(remaining_repaints - 1))
                    return
                try:
                    self.import_modal.attributes("-alpha", 1.0)
                except tk.TclError:
                    pass
                self.import_modal.grab_set()

            self.import_modal.after_idle(reveal_after_repaints)

        self.import_modal.after_idle(reveal_after_ready)

    def start_worker(self, selected_files: list[Path]) -> None:
        """Launch the import worker process."""
        file_paths = [str(path) for path in selected_files]
        ctx = mp.get_context("spawn")
        self.import_abort_flag = ctx.Event()
        self.import_result_queue = ctx.Queue(maxsize=IMPORT_RESULT_QUEUE_MAXSIZE)
        self.import_process = ctx.Process(
            target=import_worker_process,
            args=(
                file_paths,
                bool(self.parser.parse_immunity),
                self.import_abort_flag,
                self.import_result_queue,
                self.parser.death_character_name,
                self.parser.death_fallback_line,
            ),
            daemon=True,
        )
        self.import_process.start()

    def drain_events(self) -> None:
        """Drain worker-process events into the Tk-thread application queue."""
        if self.import_result_queue is None:
            return
        while True:
            try:
                event = self.import_result_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get("event")
            if event_type == "file_started":
                with self._import_status_lock:
                    self._import_status["current_file"] = event.get("file_name", "")
            elif event_type == "ops_chunk":
                ops = event.get("ops", {})
                self._pending_file_payloads.append(
                    {
                        "mutations": ops.get("mutations", []),
                        "death_snippets": ops.get("death_snippets", []),
                        "death_character_identified": ops.get("death_character_identified", []),
                        "index": event.get("index", 0),
                        "mutation_idx": 0,
                    }
                )
                if not self._is_applying_payload:
                    self._is_applying_payload = True
                    self.root.after(1, self.apply_pending_payloads_incremental)
            elif event_type == "file_completed":
                with self._import_status_lock:
                    self._import_status["files_completed"] = event.get("index", 0)
            elif event_type == "file_error":
                with self._import_status_lock:
                    errors = self._import_status.setdefault("errors", [])
                    errors.append(f"{event.get('file_name')}: {event.get('error')}")
            elif event_type == "aborted":
                with self._import_status_lock:
                    self._import_status["aborted"] = True
                    self._import_status["worker_done"] = True
            elif event_type == "done":
                with self._import_status_lock:
                    self._import_status["worker_done"] = True

    def apply_pending_payloads_incremental(self) -> None:
        """Apply completed-file payloads in small Tk-thread slices."""
        deadline = perf_counter() + (self.import_apply_frame_budget_ms / 1000.0)
        batch_size = max(1, int(self.import_apply_mutation_batch_size))
        while perf_counter() < deadline and self._pending_file_payloads:
            item = self._pending_file_payloads[0]
            mutation_idx = item["mutation_idx"]
            mutations = item["mutations"]
            if mutation_idx < len(mutations):
                batch_end = min(mutation_idx + batch_size, len(mutations))
                self.data_store.apply_mutations(mutations[mutation_idx:batch_end])
                item["mutation_idx"] = batch_end
                continue

            death_snippets = item["death_snippets"]
            if death_snippets:
                self.death_snippet_panel.add_death_events(
                    [self.death_snippet_from_payload(event) for event in death_snippets]
                )
                item["death_snippets"] = []

            identity_events = item["death_character_identified"]
            if identity_events:
                for identity_event in identity_events:
                    self.on_character_identified(
                        self.death_character_identified_from_payload(identity_event)
                    )
                item["death_character_identified"] = []

            self._pending_file_payloads.popleft()

        if self._pending_file_payloads:
            self.root.after(1, self.apply_pending_payloads_incremental)
            return
        self._is_applying_payload = False

    def poll_progress(self) -> None:
        """Refresh the modal with current import progress."""
        if not self.is_importing:
            return

        self.drain_events()
        with self._import_status_lock:
            status = dict(self._import_status)

        if self.import_status_text is not None:
            current_file = status.get("current_file") or "Preparing selected files..."
            if self._last_modal_file != current_file:
                self.import_status_text.set(f"Parsing: {current_file}")
                self._last_modal_file = current_file
        if self.import_progress_text is not None:
            files_completed = status.get("files_completed", 0)
            total_files = status.get("total_files", 0)
            if self._last_modal_files_completed != files_completed:
                self.import_progress_text.set(f"{files_completed}/{total_files} files completed")
                self._last_modal_files_completed = files_completed

        worker_done = bool(status.get("worker_done"))
        has_pending = bool(self._pending_file_payloads) or self._is_applying_payload
        if not worker_done or has_pending:
            self.import_poll_job = self.root.after(200, self.poll_progress)
            return
        self.finalize()

    def abort(self) -> None:
        """Request abort for ongoing import."""
        if not self.is_importing:
            return
        self.import_abort_event.set()
        if self.import_abort_flag is not None:
            self.import_abort_flag.set()
        if self.import_abort_button is not None:
            self.import_abort_button.config(state=tk.DISABLED)
        if self.import_status_text is not None:
            self.import_status_text.set("Aborting...")

    def finalize(self) -> None:
        """Finalize import and refresh UI state."""
        if self.import_poll_job is not None:
            self.root.after_cancel(self.import_poll_job)
            self.import_poll_job = None

        self.is_importing = False
        self.set_controls_busy(False)
        self._is_applying_payload = False
        self._pending_file_payloads.clear()

        if self.import_process is not None:
            if self.import_process.is_alive():
                self.import_process.join(timeout=0.2)
                if self.import_process.is_alive():
                    self.import_process.terminate()
            self.import_process = None
        self.import_result_queue = None
        self.import_abort_flag = None

        if self.import_modal is not None:
            progress = self.import_progressbar
            if progress is not None:
                progress.stop()
            self.import_modal.grab_release()
            self.import_modal.destroy()
            self.import_modal = None
        self.import_progressbar = None

        with self._import_status_lock:
            status = dict(self._import_status)

        self.refresh_targets()
        self.dps_panel.refresh()

        if status.get("aborted"):
            self.log_debug(
                f"Load & Parse aborted. Imported {status.get('files_completed', 0)} files before stop.",
                "warning",
            )
        elif status.get("errors"):
            show_warning_dialog(
                self.root,
                "Load & Parse Completed with Errors",
                "\n".join(status["errors"]),
                icon_path=self.get_window_icon_path(),
            )
            self.log_debug("Load & Parse completed with file errors.", "warning")
        else:
            self.log_debug(
                f"Load & Parse completed: {status.get('total_files', 0)} files.",
                "info",
            )

    def shutdown(self) -> None:
        """Abort and tear down import resources during app close."""
        if self.is_importing:
            self.import_abort_event.set()
            if self.import_abort_flag is not None:
                self.import_abort_flag.set()
            if self.import_process is not None and self.import_process.is_alive():
                self.import_process.terminate()
