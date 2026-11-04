import json
import inspect
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import wechat_ai_control.vm_window as vm_window
from wechat_ai_control.vm_window import VmWindowAdapter


class VmWindowAdapterTests(unittest.TestCase):
    def _read_status(self, path, **kwargs):
        probe = getattr(vm_window, "read_login_status", None)
        self.assertIsNotNone(probe)
        parameters = inspect.signature(probe).parameters
        for name in kwargs:
            self.assertIn(name, parameters)
        return probe(path, **kwargs)

    def test_login_status_probe_accepts_fresh_status_and_matching_session(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vm-login.json"
            path.write_text(json.dumps({
                "status": "logged_in",
                "updatedAt": (now - timedelta(seconds=10)).isoformat(),
                "sessionId": "vm-session-1",
            }), encoding="utf-8")
            self.assertTrue(self._read_status(
                path,
                max_age_seconds=90,
                expected_session_id="vm-session-1",
                now=now,
            ))

    def test_login_status_probe_rejects_stale_future_and_mismatched_status(self):
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vm-login.json"
            base = {"status": "logged_in", "sessionId": "vm-session-1"}
            path.write_text(json.dumps({
                **base,
                "updatedAt": (now - timedelta(seconds=91)).isoformat(),
            }), encoding="utf-8")
            self.assertIsNone(self._read_status(path, max_age_seconds=90, now=now))

            path.write_text(json.dumps({
                **base,
                "updatedAt": (now + timedelta(seconds=1)).isoformat(),
            }), encoding="utf-8")
            self.assertIsNone(self._read_status(path, max_age_seconds=90, now=now))

            path.write_text(json.dumps({
                **base,
                "updatedAt": (now - timedelta(seconds=1)).isoformat(),
            }), encoding="utf-8")
            self.assertIsNone(self._read_status(
                path,
                max_age_seconds=90,
                expected_session_id="different-session",
                now=now,
            ))

    def test_login_status_diagnostic_explains_safe_failure_reasons(self):
        diagnostic = getattr(vm_window, "read_login_status_diagnostic", None)
        self.assertIsNotNone(diagnostic)
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vm-login.json"
            result = diagnostic(path, now=now)
            self.assertIsNone(result.logged_in)
            self.assertEqual(result.reason, "login_status_missing")

            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(diagnostic(path, now=now).reason, "login_status_malformed")

            base = {"status": "logged_in", "sessionId": "vm-session-1"}
            path.write_text(json.dumps({
                **base,
                "updatedAt": (now - timedelta(seconds=91)).isoformat(),
            }), encoding="utf-8")
            self.assertEqual(diagnostic(path, now=now).reason, "login_status_stale")

            path.write_text(json.dumps({
                **base,
                "updatedAt": (now + timedelta(seconds=1)).isoformat(),
            }), encoding="utf-8")
            self.assertEqual(diagnostic(path, now=now).reason, "login_status_future")

            path.write_text(json.dumps({
                **base,
                "updatedAt": (now - timedelta(seconds=1)).isoformat(),
            }), encoding="utf-8")
            self.assertEqual(diagnostic(path, expected_session_id="other", now=now).reason, "login_session_mismatch")

    def test_window_snapshot_surfaces_login_diagnostic_reason_without_sensitive_data(self):
        adapter = VmWindowAdapter(
            title_pattern="Virtual WeChat",
            window_reader=lambda: [{
                "windowId": "42",
                "title": "Virtual WeChat - Chat",
                "bounds": {"left": 1, "top": 2, "right": 801, "bottom": 602},
            }],
            foreground_reader=lambda: "42",
            login_reader=lambda _window: vm_window.LoginStatusProbe(None, "login_status_stale"),
        )
        snapshot = adapter.snapshot()
        self.assertEqual(snapshot.reason, "login_status_stale")
        self.assertNotIn("Virtual WeChat", snapshot.reason)

    def test_login_status_probe_reads_only_explicit_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vm-login.json"
            path.write_text(json.dumps({"status": "logged_in"}), encoding="utf-8")
            self.assertTrue(self._read_status(path, max_age_seconds=None))

            path.write_text(json.dumps({"loggedIn": False}), encoding="utf-8")
            self.assertFalse(self._read_status(path, max_age_seconds=None))

    def test_login_status_probe_fails_closed_for_missing_or_invalid_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertIsNone(self._read_status(path, max_age_seconds=None))
            path.write_text("not-json", encoding="utf-8")
            self.assertIsNone(self._read_status(path, max_age_seconds=None))
            path.write_text(json.dumps(True), encoding="utf-8")
            self.assertIsNone(self._read_status(path))

    def test_environment_wires_explicit_login_probe_without_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vm-login.json"
            updated_at = datetime.now(timezone.utc).isoformat()
            path.write_text(json.dumps({
                "status": "logged_in",
                "updatedAt": updated_at,
                "sessionId": "vm-session-1",
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "WECHAT_VM_WINDOW_TITLE_PATTERN": "Virtual WeChat",
                "WECHAT_VM_LOGIN_STATUS_PATH": str(path),
                "WECHAT_VM_LOGIN_STATUS_MAX_AGE_SECONDS": "90",
                "WECHAT_VM_SESSION_ID": "vm-session-1",
            }, clear=False):
                with mock.patch.object(VmWindowAdapter, "_default_window_reader", return_value=[{
                        "windowId": "42",
                        "title": "Virtual WeChat - Chat",
                        "className": "WeChat",
                        "bounds": {"left": 1, "top": 2, "right": 801, "bottom": 602},
                }]), mock.patch.object(VmWindowAdapter, "_default_foreground_reader", return_value="42"):
                    adapter = VmWindowAdapter.from_environment()
            snapshot = adapter.snapshot()
            self.assertTrue(snapshot.automation_ready)
            self.assertTrue(snapshot.logged_in)

    def test_missing_match_is_unknown_and_safe(self):
        adapter = VmWindowAdapter(
            title_pattern="Virtual WeChat",
            window_reader=lambda: [],
            foreground_reader=lambda: None,
            login_reader=lambda _window: True,
        )
        snapshot = adapter.snapshot()
        self.assertEqual(snapshot.status, "unknown")
        self.assertFalse(snapshot.automation_ready)
        self.assertEqual(snapshot.reason, "vm_window_not_found")

    def test_login_probe_missing_is_not_ready(self):
        adapter = VmWindowAdapter(
            title_pattern="Virtual WeChat",
            window_reader=lambda: [{
                "windowId": "42",
                "title": "Virtual WeChat - Chat",
                "className": "Qt5152QWindowIcon",
                "bounds": {"left": 1, "top": 2, "right": 801, "bottom": 602},
            }],
            foreground_reader=lambda: "42",
            login_reader=None,
        )
        snapshot = adapter.snapshot()
        self.assertEqual(snapshot.status, "unknown")
        self.assertFalse(snapshot.automation_ready)
        self.assertEqual(snapshot.reason, "login_state_probe_unconfigured")

    def test_matching_window_exposes_metadata_without_side_effects(self):
        calls = []
        adapter = VmWindowAdapter(
            title_pattern="Virtual WeChat",
            window_reader=lambda: [{
                "windowId": "42",
                "title": "Virtual WeChat - 张三",
                "className": "WeChat",
                "bounds": {"left": 1, "top": 2, "right": 801, "bottom": 602},
            }],
            foreground_reader=lambda: "42",
            login_reader=lambda window: calls.append(window["windowId"]) or True,
        )
        snapshot = adapter.snapshot()
        self.assertEqual(snapshot.status, "ready")
        self.assertTrue(snapshot.automation_ready)
        self.assertEqual(snapshot.chat_title, "张三")
        self.assertTrue(snapshot.is_foreground)
        self.assertEqual(calls, ["42"])


if __name__ == "__main__":
    unittest.main()
