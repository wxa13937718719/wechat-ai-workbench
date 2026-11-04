import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig


class FakeRuntime:
    def status(self):
        return {
            "activeWriter": {"pid": 1234},
            "unlocked": 0,
            "pendingChats": 0,
            "pendingMessages": 0,
            "paused": False,
        }

    def config_status(self):
        return {
            "saved": {"reloadToken": 2, "source": "runtime", "lastError": None},
            "effective": {
                "reloadToken": 1,
                "source": "runtime",
                "loadedAt": "2026-09-20T00:00:00+00:00",
                "lastError": None,
            },
            "health": "pending_reload",
        }


class RuntimeStatusApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app = create_app(AppConfig(state_dir=Path(self.tmp.name)), runtime=FakeRuntime())
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_runtime_api_distinguishes_saved_and_effective_revision(self):
        response = self.client.get("/api/config/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue({"saved", "effective", "health"} <= payload.keys())
        self.assertIn("reloadToken", payload["saved"])
        self.assertIn("reloadToken", payload["effective"])
        self.assertEqual(payload["health"], "pending_reload")

    def test_runtime_endpoint_keeps_existing_keys_and_adds_config_status(self):
        payload = self.client.get("/api/runtime").json()
        self.assertIn("settings", payload)
        self.assertIn("status", payload)
        self.assertIn("saved", payload)
        self.assertIn("effective", payload)
        self.assertIn("health", payload)

    def test_runtime_page_has_effective_config_status_region(self):
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="runtime-config-status"', response.text)


if __name__ == "__main__":
    unittest.main()
