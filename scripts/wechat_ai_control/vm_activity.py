"""Read-only VM window activity observation."""

from __future__ import annotations

import ctypes
import os
import time
from typing import Callable

from .interaction import ActivityEvent


def _default_cursor_reader() -> tuple[int, int] | None:
    if os.name != "nt":
        return None

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        return None
    return int(point.x), int(point.y)


def _default_input_tick_reader() -> int | None:
    if os.name != "nt":
        return None

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return int(info.dwTime)


class VmActivitySource:
    """Turn read-only window metadata changes into human activity events."""

    def __init__(
        self,
        window_adapter,
        *,
        cursor_reader: Callable[[], tuple[int, int] | None] | None = None,
        input_tick_reader: Callable[[], int | None] | None = None,
        clock: Callable[[], float] | None = None,
        automation_suppression_seconds: float = 2.0,
    ):
        self.window_adapter = window_adapter
        self.cursor_reader = cursor_reader or _default_cursor_reader
        self.input_tick_reader = input_tick_reader or _default_input_tick_reader
        self.clock = clock or time.monotonic
        self.automation_suppression_seconds = max(0.0, float(automation_suppression_seconds))
        self._initialized = False
        self._window_id: str | None = None
        self._foreground = False
        self._was_cursor_inside = False
        self._input_tick: int | None = None
        self._suppress_next_input = False
        self._automation_marked_at: float | None = None

    @staticmethod
    def _is_cursor_inside(bounds, cursor) -> bool:
        if not isinstance(bounds, dict) or not cursor or len(cursor) != 2:
            return False
        try:
            left = int(bounds["left"])
            top = int(bounds["top"])
            right = int(bounds["right"])
            bottom = int(bounds["bottom"])
            x, y = int(cursor[0]), int(cursor[1])
        except (KeyError, TypeError, ValueError):
            return False
        return left <= x < right and top <= y < bottom

    def _safe_cursor(self):
        try:
            return self.cursor_reader()
        except Exception:
            return None

    def _safe_input_tick(self):
        try:
            return self.input_tick_reader()
        except Exception:
            return None

    def mark_automation_activity(self) -> None:
        """Suppress the next observed system input tick as daemon-owned activity."""
        self._suppress_next_input = True
        self._automation_marked_at = self.clock()

    def poll(self) -> list[ActivityEvent]:
        now = self.clock()
        try:
            window = self.window_adapter.snapshot()
        except Exception:
            self._initialized = True
            self._window_id = None
            self._foreground = False
            self._was_cursor_inside = False
            self._input_tick = self._safe_input_tick()
            return [ActivityEvent(kind="unknown", source="vm_activity_observer", at=now)]

        window_id = str(getattr(window, "window_id", None) or "") or None
        cursor_inside = self._is_cursor_inside(
            getattr(window, "bounds", None),
            self._safe_cursor(),
        ) if window_id else False
        foreground = bool(window_id and getattr(window, "is_foreground", False))
        input_tick = self._safe_input_tick()
        events: list[ActivityEvent] = []

        if not window_id:
            self._initialized = True
            self._window_id = None
            self._foreground = False
            self._was_cursor_inside = False
            self._input_tick = input_tick
            return events

        first_observation = not self._initialized or self._window_id != window_id
        if first_observation:
            if foreground:
                events.append(ActivityEvent(kind="window_focus", source="vm_wechat_user", at=now))
            if cursor_inside:
                events.append(ActivityEvent(kind="mouse_enter", source="vm_wechat_user", at=now))
        else:
            if foreground and not self._foreground:
                events.append(ActivityEvent(kind="window_focus", source="vm_wechat_user", at=now))
            if cursor_inside and not self._was_cursor_inside:
                events.append(ActivityEvent(kind="mouse_enter", source="vm_wechat_user", at=now))

        if self._automation_marked_at is not None and now - self._automation_marked_at > self.automation_suppression_seconds:
            self._suppress_next_input = False
            self._automation_marked_at = None
        input_changed = input_tick is not None and self._input_tick is not None and input_tick != self._input_tick
        if input_changed and (foreground or cursor_inside):
            if self._suppress_next_input:
                self._suppress_next_input = False
                self._automation_marked_at = None
            else:
                events.append(ActivityEvent(kind="user_input", source="vm_wechat_user", at=now))

        self._initialized = True
        self._window_id = window_id
        self._foreground = foreground
        self._was_cursor_inside = cursor_inside
        self._input_tick = input_tick
        return events
