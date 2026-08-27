"""Bounded activation routing and the ASUS TUF Right-Ctrl double-tap hook."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable
from typing import Protocol, cast

from personal_ai_os.voice.contracts import ActivationSource


class ActivationUnavailable(RuntimeError):
    """The local activation mechanism is unavailable on this host."""


class _User32(Protocol):
    """Narrow Windows API surface used by the Right-Ctrl detector."""

    def GetAsyncKeyState(self, virtual_key: int) -> int:
        """Return the current high-order key state for one virtual key."""


def _resolve_user32() -> _User32:
    """Resolve only the one typed user32 API needed by the Windows path."""

    if sys.platform != "win32":
        raise ActivationUnavailable("Right Ctrl activation is Windows-only")
    windll = getattr(ctypes, "windll", None)
    user32 = getattr(windll, "user32", None)
    get_async_key_state = getattr(user32, "GetAsyncKeyState", None)
    if not callable(get_async_key_state):
        raise ActivationUnavailable("Windows user32 GetAsyncKeyState is unavailable")
    return cast(_User32, user32)


class ActivationRouter:
    """Route every activation source into one owner-supplied callback."""

    def __init__(self, activate: Callable[[ActivationSource], None]) -> None:
        self._activate = activate

    def wake_word(self) -> None:
        self._activate(ActivationSource.WAKE_WORD)

    def right_ctrl_double_tap(self) -> None:
        self._activate(ActivationSource.RIGHT_CTRL_DOUBLE_TAP)

    def ptt(self) -> None:
        self._activate(ActivationSource.PTT)


class WindowsRightCtrlDoubleTap:
    """Monitor only Right Ctrl transitions in the current Windows user session.

    This deliberately uses ``GetAsyncKeyState`` for one virtual key rather than
    installing a general keyboard hook or recording key content. It requires no
    administrator privilege and is unavailable on non-Windows hosts.
    """

    _RIGHT_CTRL = 0xA3

    def __init__(self, callback: Callable[[], None], *, interval_seconds: float = 0.01) -> None:
        if sys.platform != "win32":
            raise ActivationUnavailable("Right Ctrl activation is Windows-only")
        if interval_seconds <= 0:
            raise ValueError("activation polling interval must be positive")
        self._callback: Callable[[], None] = callback
        self._interval_seconds: float = interval_seconds
        self._stop: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None
        self._user32: _User32 = _resolve_user32()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bmo-right-ctrl", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        was_down = False
        last_tap = 0.0
        while not self._stop.is_set():
            is_down = bool(self._user32.GetAsyncKeyState(self._RIGHT_CTRL) & 0x8000)
            if is_down and not was_down:
                now = time.monotonic()
                if now - last_tap <= 0.35:
                    last_tap = 0.0
                    self._callback()
                else:
                    last_tap = now
            was_down = is_down
            self._stop.wait(self._interval_seconds)


__all__ = ["ActivationRouter", "ActivationUnavailable", "WindowsRightCtrlDoubleTap"]
