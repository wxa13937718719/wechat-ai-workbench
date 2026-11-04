import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fastapi.testclient import TestClient

from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig


class ControlApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = AppConfig(state_dir=Path(self.tmp.name), local_token="test-token")
        self.client = TestClient(create_app(self.config))

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_requires_local_token_when_configured(self):
        denied = self.client.get("/api/health")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.json()["error"]["code"], "unauthorized")
        response = self.client.get("/api/health", headers={"X-Local-Token": "test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_dashboard_shell_returns(self):
        response = self.client.get("/", headers={"X-Local-Token": "test-token"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("微信 AI 控制台", response.text)

    def test_validation_errors_use_api_error_contract(self):
        response = self.client.get("/api/updates?since=not-a-number", headers={"X-Local-Token": "test-token"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertFalse(response.json()["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
