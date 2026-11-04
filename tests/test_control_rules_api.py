import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig


class RulesApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(AppConfig(state_dir=Path(self.tmp.name)))
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rules_apply_and_rollback(self):
        response = self.client.post("/api/rules/apply", json={"revision": 0, "rules": [{"id": "r1", "scope": "global", "instruction": "活泼一点"}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rules"][0]["id"], "r1")
        rollback = self.client.post("/api/rules/rollback", json={"revision": 0})
        self.assertEqual(rollback.status_code, 200)
        self.assertEqual(rollback.json()["rules"], [])

    def test_command_parse_requires_known_target(self):
        response = self.client.post("/api/commands/parse", json={"text": "以后活泼一点"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("operations", response.json())


if __name__ == "__main__":
    unittest.main()
