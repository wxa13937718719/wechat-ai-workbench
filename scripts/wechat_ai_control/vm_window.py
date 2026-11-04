"""Read-only observation of the configured virtual-machine WeChat window."""

from __future__ import annotations

import ctypes
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class VmWindowSnapshot:
    status: str
    window_id: str | None
    title: str
    chat_title: str
    bounds: dict[str, int] | None
    is_foreground: bool
    logged_in: bool | None
    automation_ready: bool
    reason: str
    observed_at: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["windowId"] = payload.pop("window_id")
        payload["chatTitle"] = payload.pop("chat_title")
        payload["isForeground"] = payload.pop("is_foreground")
        payload["loggedIn"] = payload.pop("logged_in")
        payload["automationReady"] = payload.pop("automation_ready")
        payload["observedAt"] = payload.pop("observed_at")
        return payload


@dataclass(frozen=True)
class LoginStatusProbe:
    logged_in: bool | None
    reason: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_snapshot(reason: str) -> VmWindowSnapshot:
    return VmWindowSnapshot(
        status="unknown",
        window_id=None,
        title="",
        chat_title="",
        bounds=None,
        is_foreground=False,
        logged_in=None,
        automation_ready=False,
        reason=reason,
        observed_at=_now(),
    )


def _chat_title(title: str) -> str:
    value = str(title or "").strip()
    if " - " in value:
        return value.rsplit(" - ", 1)[-1].strip()
    return value


def _parse_status_timestamp(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def read_login_status_diagnostic(
    path: str | os.PathLike[str],
    *,
    max_age_seconds: int | float | None = 90,
    expected_session_id: str | None = None,
    now: datetime | None = None,
) -> LoginStatusProbe:
    """Read VM login status and return only a safe, non-sensitive failure reason."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LoginStatusProbe(None, "login_status_missing")
    except (OSError, TypeError):
        return LoginStatusProbe(None, "login_status_missing")
    except (ValueError, json.JSONDecodeError):
        return LoginStatusProbe(None, "login_status_malformed")
    if isinstance(payload, bool):
        if max_age_seconds is None and expected_session_id is None:
            return LoginStatusProbe(payload)
        return LoginStatusProbe(None, "login_status_malformed")
    if not isinstance(payload, dict):
        return LoginStatusProbe(None, "login_status_malformed")
    if max_age_seconds is not None:
        if isinstance(max_age_seconds, bool):
            return LoginStatusProbe(None, "login_status_malformed")
        try:
            max_age = float(max_age_seconds)
        except (TypeError, ValueError):
            return LoginStatusProbe(None, "login_status_malformed")
        if max_age < 0:
            return LoginStatusProbe(None, "login_status_malformed")
        updated_at = _parse_status_timestamp(payload.get("updatedAt"))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            return LoginStatusProbe(None, "login_status_malformed")
        current = current.astimezone(timezone.utc)
        if updated_at is None:
            return LoginStatusProbe(None, "login_status_malformed")
        age = (current - updated_at).total_seconds()
        if age < 0:
            return LoginStatusProbe(None, "login_status_future")
        if age > max_age:
            return LoginStatusProbe(None, "login_status_stale")
    if expected_session_id is not None:
        session_id = payload.get("sessionId")
        if not isinstance(session_id, str) or not session_id or session_id != expected_session_id:
            return LoginStatusProbe(None, "login_session_mismatch")
    logged_in = payload.get("loggedIn")
    if isinstance(logged_in, bool):
        return LoginStatusProbe(logged_in)
    status = str(payload.get("status") or "").strip().casefold()
    if status in {"logged_in", "logged-in", "authenticated", "signed_in", "signed-in"}:
        return LoginStatusProbe(True)
    if status in {"logged_out", "logged-out", "unauthenticated", "signed_out", "signed-out"}:
        return LoginStatusProbe(False)
    return LoginStatusProbe(None, "login_status_malformed")


def read_login_status(
    path: str | os.PathLike[str],
    *,
    max_age_seconds: int | float | None = 90,
    expected_session_id: str | None = None,
    now: datetime | None = None,
) -> bool | None:
    """Read an explicit VM-side login status without touching the VM window."""
    return read_login_status_diagnostic(
        path,
        max_age_seconds=max_age_seconds,
        expected_session_id=expected_session_id,
        now=now,
    ).logged_in


class VmWindowAdapter:
    """Observe one explicitly configured VM window without changing focus."""

    def __init__(
        self,
        title_pattern: str | None = None,
        *,
        window_reader: Callable[[], list[dict]] | None = None,
        foreground_reader: Callable[[], str | None] | None = None,
        login_reader: Callable[[dict], bool | None] | None = None,
    ):
        self.title_pattern = title_pattern
        self.window_reader = window_reader or self._default_window_reader
        self.foreground_reader = foreground_reader or self._default_foreground_reader
        self.login_reader = login_reader

    @classmethod
    def from_environment(cls) -> "VmWindowAdapter":
        title_pattern = os.environ.get("WECHAT_VM_WINDOW_TITLE_PATTERN") or None
        status_path = os.environ.get("WECHAT_VM_LOGIN_STATUS_PATH") or ""
        login_reader = None
        if status_path.strip():
            expanded_path = os.path.expandvars(status_path.strip())
            try:
                max_age_seconds = int(os.environ.get("WECHAT_VM_LOGIN_STATUS_MAX_AGE_SECONDS", "90"))
            except (TypeError, ValueError):
                max_age_seconds = 90
            max_age_seconds = max(1, min(max_age_seconds, 3600))
            expected_session_id = os.environ.get("WECHAT_VM_SESSION_ID") or None
            login_reader = lambda _window: read_login_status_diagnostic(
                expanded_path,
                max_age_seconds=max_age_seconds,
                expected_session_id=expected_session_id,
            )
        return cls(title_pattern, login_reader=login_reader)

    @staticmethod
    def _default_window_reader() -> list[dict]:
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        windows: list[dict] = []

        class Rect(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            title_length = user32.GetWindowTextLengthW(hwnd)
            title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            rect = Rect()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            windows.append({
                "windowId": str(int(hwnd)),
                "title": title_buffer.value,
                "className": class_buffer.value,
                "bounds": {
                    "left": int(rect.left),
                    "top": int(rect.top),
                    "right": int(rect.right),
                    "bottom": int(rect.bottom),
                },
            })
            return True

        user32.EnumWindows(callback_type(callback), 0)
        return windows

    @staticmethod
    def _default_foreground_reader() -> str | None:
        if os.name != "nt":
            return None
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return str(int(hwnd)) if hwnd else None

    def _matching_windows(self) -> tuple[list[dict], str | None]:
        if not self.title_pattern:
            return [], "window_match_not_configured"
        try:
            pattern = re.compile(self.title_pattern, re.IGNORECASE)
        except re.error:
            return [], "window_match_pattern_invalid"
        try:
            windows = self.window_reader() or []
        except Exception:
            return [], "window_reader_failed"
        matches = [
            window for window in windows
            if isinstance(window, dict) and pattern.search(str(window.get("title") or ""))
        ]
        return matches, None

    def snapshot(self) -> VmWindowSnapshot:
        matches, early_reason = self._matching_windows()
        if early_reason:
            return _empty_snapshot(early_reason)
        if not matches:
            return _empty_snapshot("vm_window_not_found")
        if len(matches) > 1:
            return _empty_snapshot("vm_window_ambiguous")

        window = matches[0]
        window_id = str(window.get("windowId") or "") or None
        title = str(window.get("title") or "")
        try:
            foreground_id = self.foreground_reader()
        except Exception:
            foreground_id = None
        is_foreground = bool(window_id and str(foreground_id or "") == window_id)
        if self.login_reader is None:
            return VmWindowSnapshot(
                status="unknown",
                window_id=window_id,
                title=title,
                chat_title=_chat_title(title),
                bounds=window.get("bounds") if isinstance(window.get("bounds"), dict) else None,
                is_foreground=is_foreground,
                logged_in=None,
                automation_ready=False,
                reason="login_state_probe_unconfigured",
                observed_at=_now(),
            )
        try:
            probe = self.login_reader(window)
            if isinstance(probe, LoginStatusProbe):
                logged_in = probe.logged_in
                probe_reason = probe.reason
            else:
                logged_in = probe
                probe_reason = ""
        except Exception:
            logged_in = None
            probe_reason = "login_state_probe_failed"
        if logged_in is False:
            status = "logged_out"
            reason = "vm_logged_out"
        elif logged_in is True:
            status = "ready"
            reason = ""
        else:
            status = "unknown"
            reason = probe_reason or "login_state_probe_failed"
        return VmWindowSnapshot(
            status=status,
            window_id=window_id,
            title=title,
            chat_title=_chat_title(title),
            bounds=window.get("bounds") if isinstance(window.get("bounds"), dict) else None,
            is_foreground=is_foreground,
            logged_in=logged_in,
            automation_ready=status == "ready",
            reason=reason,
            observed_at=_now(),
        )
