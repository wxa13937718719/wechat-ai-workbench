import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig
from wechat_ai_control.runtime import RuntimeBridge


TRANSFER_STATUS = {
    "transactionId": "tx-redacted",
    "source": "vm_bridge_commit",
    "stage": "locked",
    "active": True,
    "itemCount": 2,
    "startedAt": 100.0,
    "finishedAt": None,
    "outcome": None,
    "errorCode": None,
    "enforcement": "observe_only",
}


class FakeTransferRuntime:
    def status(self):
        return {
            "activeWriter": {"pid": 1234},
            "unlocked": 0,
            "pendingChats": 0,
            "pendingMessages": 0,
            "paused": False,
        }

    def transfer_status(self):
        return dict(TRANSFER_STATUS)


class ControlTransferStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            runtime=FakeTransferRuntime(),
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def test_transfer_status_endpoint_is_redacted_and_read_only(self):
        response = self.client.get("/api/transfers/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), TRANSFER_STATUS)
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn("filePath", serialized)
        self.assertNotIn("filename", serialized)
        self.assertNotEqual(self.client.post("/api/transfers/status").status_code, 200)

    def test_api_status_keeps_existing_keys_and_adds_transfer(self):
        payload = self.client.get("/api/status").json()
        self.assertIn("activeWriter", payload)
        self.assertEqual(payload["transfer"], TRANSFER_STATUS)

    def test_settings_surface_marks_transfer_as_observation_only(self):
        page = self.client.get("/settings")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="transfer-status"', page.text)
        self.assertIn("仅观察，未接入文件发送", page.text)

    def test_unconfigured_runtime_bridge_fails_closed(self):
        bridge = RuntimeBridge(
            store=None,
            wechat=None,
            state_path=Path(self.tmp.name) / "state.json",
        )
        status = bridge.transfer_status()
        self.assertEqual(status["source"], "unknown")
        self.assertEqual(status["stage"], "idle")
        self.assertFalse(status["active"])
        self.assertEqual(status["enforcement"], "observe_only")


if __name__ == "__main__":
    unittest.main()
