import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import wechat_ai_control.app as app_module
from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig
from wechat_ai_control.runtime import RuntimeBridge


SAFE_INTERACTION = {
    "state": "PAUSED_UNKNOWN",
    "reason": "vm_window_not_found",
    "canAutomate": False,
    "enforcement": "observe_only",
    "lastHumanActionAt": None,
    "idleDeadlineAt": None,
    "countdownDeadlineAt": None,
    "idleRemainingSeconds": None,
    "countdownRemainingSeconds": None,
    "transactionId": None,
    "leaseId": None,
    "leaseChatId": None,
    "window": {
        "status": "unknown",
        "windowId": None,
        "title": "",
        "chatTitle": "",
        "bounds": None,
        "isForeground": False,
        "loggedIn": None,
        "automationReady": False,
        "reason": "vm_window_not_found",
        "observedAt": "2026-09-21T00:00:00+00:00",
    },
}


class FakeRuntimeWithInteraction:
    def status(self):
        return {
            "activeWriter": {"pid": 1234},
            "unlocked": 0,
            "pendingChats": 0,
            "pendingMessages": 0,
            "paused": False,
            "interaction": SAFE_INTERACTION,
        }

    def interaction_status(self):
        return SAFE_INTERACTION

    def config_status(self):
        return {
            "saved": {"reloadToken": 1, "source": "runtime", "lastError": None},
            "effective": {"reloadToken": 1, "source": "runtime", "loadedAt": "now", "lastError": None},
            "health": "healthy",
        }


class SnapshotWithoutEnforcement:
    def to_dict(self):
        payload = dict(SAFE_INTERACTION)
        payload.pop("enforcement", None)
        return payload


class FakeArbiter:
    def observe(self):
        return SnapshotWithoutEnforcement()


class ControlInteractionStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            runtime=FakeRuntimeWithInteraction(),
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def test_interaction_endpoint_and_settings_surface_are_safe(self):
        response = self.client.get("/api/interaction")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["state"], "PAUSED_UNKNOWN")
        self.assertFalse(payload["canAutomate"])
        self.assertEqual(payload["enforcement"], "observe_only")
        self.assertNotIn("filePath", json.dumps(payload))
        page = self.client.get("/settings")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="interaction-status"', page.text)
        self.assertIn('id="vm-diagnostics"', page.text)
        script = self.client.get("/static/js/control-pages.js").text
        self.assertIn("login_status_stale", script)
        self.assertIn("vm-diagnostics", script)

    def test_runtime_status_keeps_existing_keys_and_adds_interaction(self):
        payload = self.client.get("/api/status").json()
        self.assertIn("activeWriter", payload)
        self.assertIn("interaction", payload)
        self.assertFalse(payload["interaction"]["canAutomate"])

    def test_runtime_bridge_marks_interaction_as_observation_only(self):
        bridge = RuntimeBridge(store=None, wechat=None, state_path=Path(self.tmp.name) / "state.json", interaction=FakeArbiter())
        self.assertEqual(bridge.interaction_status()["enforcement"], "observe_only")

    def test_default_runtime_constructs_read_only_vm_activity_source(self):
        with mock.patch.object(app_module, "VmActivitySource") as activity_source:
            app_module.create_app(AppConfig(state_dir=Path(self.tmp.name) / "default-runtime"))
        activity_source.assert_called_once()


if __name__ == "__main__":
    unittest.main()
