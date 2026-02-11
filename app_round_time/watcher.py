"""Windows directory watcher using ReadDirectoryChangesW."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Optional


FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
FILE_NOTIFY_CHANGE_SIZE = 0x00000008

THREAD_PRIORITY_HIGHEST = 2

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

FindFirstChangeNotificationW = kernel32.FindFirstChangeNotificationW
FindFirstChangeNotificationW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL, wintypes.DWORD]
FindFirstChangeNotificationW.restype = wintypes.HANDLE

FindNextChangeNotification = kernel32.FindNextChangeNotification
FindNextChangeNotification.argtypes = [wintypes.HANDLE]
FindNextChangeNotification.restype = wintypes.BOOL

FindCloseChangeNotification = kernel32.FindCloseChangeNotification
FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
FindCloseChangeNotification.restype = wintypes.BOOL

WaitForSingleObject = kernel32.WaitForSingleObject
WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
WaitForSingleObject.restype = wintypes.DWORD

GetCurrentThread = kernel32.GetCurrentThread
GetCurrentThread.argtypes = []
GetCurrentThread.restype = wintypes.HANDLE

SetThreadPriority = kernel32.SetThreadPriority
SetThreadPriority.argtypes = [wintypes.HANDLE, wintypes.INT]
SetThreadPriority.restype = wintypes.BOOL

SetThreadAffinityMask = kernel32.SetThreadAffinityMask
DWORD_PTR = ctypes.c_size_t
SetThreadAffinityMask.argtypes = [wintypes.HANDLE, DWORD_PTR]
SetThreadAffinityMask.restype = DWORD_PTR

GetLastError = kernel32.GetLastError
GetLastError.argtypes = []
GetLastError.restype = wintypes.DWORD

WAIT_OBJECT_0 = 0x00000000
WAIT_FAILED = 0xFFFFFFFF
INFINITE = 0xFFFFFFFF


class DirectoryWatcher:
    def __init__(
        self,
        directory: str,
        on_change: Callable[[], None],
        high_priority: bool = True,
        affinity_cpu: Optional[int] = None,
        debug: bool = False,
    ) -> None:
        self.directory = directory
        self.on_change = on_change
        self.high_priority = high_priority
        self.affinity_cpu = affinity_cpu
        self.debug = debug
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._notify_handle: Optional[int] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="DirectoryWatcher", daemon=True)
        self._thread.start()
        if self.debug:
            print("Watcher thread started.", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _set_thread_priority(self) -> None:
        if not self.high_priority:
            return
        try:
            thread_handle = GetCurrentThread()
            SetThreadPriority(thread_handle, THREAD_PRIORITY_HIGHEST)
        except Exception:
            pass

    def _set_thread_affinity(self) -> None:
        if self.affinity_cpu is None:
            return
        try:
            if self.affinity_cpu < 0:
                return
            mask = 1 << int(self.affinity_cpu)
            thread_handle = GetCurrentThread()
            result = SetThreadAffinityMask(thread_handle, mask)
            if not result:
                err = GetLastError()
                print(f"Warning: failed to set thread affinity (cpu={self.affinity_cpu}, err={err}).", flush=True)
        except Exception:
            pass

    def _run(self) -> None:
        self._set_thread_priority()
        self._set_thread_affinity()

        notify_filter = (
            FILE_NOTIFY_CHANGE_FILE_NAME
            | FILE_NOTIFY_CHANGE_DIR_NAME
            | FILE_NOTIFY_CHANGE_LAST_WRITE
            | FILE_NOTIFY_CHANGE_SIZE
        )
        handle = FindFirstChangeNotificationW(self.directory, False, notify_filter)
        if handle == wintypes.HANDLE(-1).value or handle == 0:
            err = GetLastError()
            print(f"Error: failed to watch directory '{self.directory}' (err={err}).", flush=True)
            return

        self._notify_handle = handle
        try:
            while not self._stop_event.is_set():
                wait = WaitForSingleObject(handle, INFINITE)
                if wait == WAIT_FAILED:
                    err = GetLastError()
                    print(f"Warning: WaitForSingleObject failed (err={err}).", flush=True)
                    continue
                if self.debug:
                    print("Watcher change detected.", flush=True)
                try:
                    self.on_change()
                except Exception:
                    pass
                FindNextChangeNotification(handle)
        finally:
            self._notify_handle = None
            FindCloseChangeNotification(handle)
