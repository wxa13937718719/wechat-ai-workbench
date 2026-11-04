import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.config_store import ConfigStore
from wechat_ai_control.providers import ProviderRegistry


class FakeCredentials:
    def __init__(self):
        self.values = {}

    def set(self, provider_id, key):
        self.values[provider_id] = key

    def get(self, provider_id):
        return self.values.get(provider_id)

    def delete(self, provider_id):
        self.values.pop(provider_id, None)


class ProviderRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.credentials = FakeCredentials()
        self.providers = ProviderRegistry(
            self.store,
            self.credentials,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def handler(self, request):
        if request.url.path.endswith("/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "llama3"}]})
        return httpx.Response(404)

    def test_openai_compatible_discovery_caches_models_without_key_leak(self):
        result = self.providers.upsert_provider({
            "id": "siliconflow",
            "kind": "openai_compatible",
            "name": "SiliconFlow",
            "base_url": "https://api.siliconflow.cn",
        }, api_key="sk-secret")
        self.assertEqual(result["id"], "siliconflow")
        models = self.providers.discover_models("siliconflow")
        self.assertEqual(models, ["model-a", "model-b"])
        raw = self.store.providers_path.read_text(encoding="utf-8")
        self.assertNotIn("sk-secret", raw)

    def test_ollama_discovery(self):
        self.providers.upsert_provider({"id": "ollama", "kind": "ollama", "name": "Ollama", "base_url": "http://127.0.0.1:11434"})
        self.assertEqual(self.providers.discover_models("ollama"), ["llama3"])

    def test_unknown_provider_raises(self):
        with self.assertRaises(KeyError):
            self.providers.discover_models("missing")


if __name__ == "__main__":
    unittest.main()
