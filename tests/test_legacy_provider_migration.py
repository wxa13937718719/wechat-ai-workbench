import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.config_store import ConfigStore


class FakeCredentials:
    def __init__(self):
        self.values = {}

    def set(self, provider_id, value):
        self.values[provider_id] = value

    def get(self, provider_id):
        return self.values.get(provider_id)


class UnavailableCredentials:
    def set(self, provider_id, value):
        raise RuntimeError("credential store unavailable")


class LegacyProviderMigrationTests(unittest.TestCase):
    def test_legacy_provider_is_imported_without_key_in_json(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            legacy = root_path / "siliconflow.json"
            legacy.write_text(json.dumps({
                "apiKey": "secret-test-key",
                "baseUrl": "https://custom.siliconflow.cn/v1",
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "visionModel": "Qwen/Qwen3-VL-8B-Instruct",
            }), encoding="utf-8")
            credentials = FakeCredentials()
            provider = ConfigStore(root_path).ensure_legacy_provider(legacy, credentials)
            stored = (root_path / "control" / "providers.json").read_text(encoding="utf-8")
            self.assertEqual(provider["id"], "siliconflow")
            self.assertEqual(credentials.get("siliconflow"), "secret-test-key")
            self.assertNotIn("secret-test-key", stored)
            self.assertNotIn("apiKey", stored)
            self.assertIn("https://custom.siliconflow.cn", stored)

    def test_missing_legacy_key_does_not_create_fake_credential(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "siliconflow.json"
            path.write_text(json.dumps({"model": "legacy-model"}), encoding="utf-8")
            credentials = FakeCredentials()
            provider = ConfigStore(Path(root)).ensure_legacy_provider(path, credentials)
            self.assertEqual(provider["models"], ["legacy-model"])
            self.assertIsNone(credentials.get("siliconflow"))

    def test_unavailable_credential_store_does_not_break_migration_or_leak_key(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            path = root_path / "siliconflow.json"
            path.write_text(json.dumps({"apiKey": "secret-test-key", "model": "legacy-model"}), encoding="utf-8")
            provider = ConfigStore(root_path).ensure_legacy_provider(path, UnavailableCredentials())
            stored = (root_path / "control" / "providers.json").read_text(encoding="utf-8")
            self.assertFalse(provider["credentialStored"])
            self.assertNotIn("secret-test-key", stored)
            self.assertEqual(json.loads(stored)["providers"][0]["credential_status"], "unavailable")

    def test_existing_provider_keeps_display_fields_and_models(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = ConfigStore(root_path)
            store.write_providers({"providers": [{
                "id": "siliconflow",
                "kind": "siliconflow",
                "name": "我的模型服务",
                "base_url": "https://custom.example",
                "credential_ref": "custom-key",
                "models": ["existing-model"],
                "enabled": False,
            }]})
            legacy = root_path / "siliconflow.json"
            legacy.write_text(json.dumps({
                "model": "new-model",
                "visionModel": "existing-model",
                "baseUrl": "https://api.siliconflow.cn/v1",
            }), encoding="utf-8")
            provider = store.ensure_legacy_provider(legacy, FakeCredentials())
            stored = store.read_providers()["providers"][0]
            self.assertEqual(stored["name"], "我的模型服务")
            self.assertEqual(stored["base_url"], "https://custom.example")
            self.assertEqual(stored["credential_ref"], "custom-key")
            self.assertFalse(stored["enabled"])
            self.assertEqual(stored["models"], ["existing-model", "new-model"])
            self.assertEqual(provider["models"], ["existing-model", "new-model"])

    def test_api_provider_listing_never_returns_legacy_api_key(self):
        from fastapi.testclient import TestClient
        from wechat_ai_control.app import create_app
        from wechat_ai_control.models import AppConfig

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            (root_path / "siliconflow.json").write_text(json.dumps({
                "apiKey": "secret-test-key",
                "model": "Qwen/Qwen2.5-7B-Instruct",
            }), encoding="utf-8")
            client = TestClient(create_app(AppConfig(state_dir=root_path)))
            response = client.get("/api/providers")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("apiKey", response.text)
            self.assertNotIn("secret-test-key", response.text)


if __name__ == "__main__":
    unittest.main()
