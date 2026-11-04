import importlib.util
import tempfile
import unittest
from pathlib import Path

import httpx

GATEWAY_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_control" / "model_gateway.py"


def load_gateway():
    spec = importlib.util.spec_from_file_location("wechat_ai_control_model_gateway", GATEWAY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRegistry:
    def list_providers(self):
        return [
            type("P", (), {"id": "openai", "kind": "openai_compatible", "base_url": "https://example.test", "models": ["m1"]})(),
            type("P", (), {"id": "ollama", "kind": "ollama", "base_url": "http://127.0.0.1:11434", "models": ["llama3"]})(),
        ]

    def _get(self, provider_id):
        for provider in self.list_providers():
            if provider.id == provider_id:
                return provider
        raise KeyError(provider_id)

    def credential_store(self):
        return None


class ModelGatewayTests(unittest.TestCase):
    def handler(self, request):
        if request.url.host == "example.test":
            return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}})
        if request.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={"message": {"content": "ollama"}})
        return httpx.Response(404)

    def test_openai_compatible_completion(self):
        gateway_mod = load_gateway()
        gateway = gateway_mod.ModelGateway(
            registry=FakeRegistry(),
            routes={"text_reply": {"primary": {"provider_id": "openai", "model": "m1"}, "fallbacks": []}},
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            credential_lookup=lambda provider_id: None,
        )
        result = gateway.complete("text_reply", [{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.provider_id, "openai")
        self.assertEqual(result.model, "m1")

    def test_ollama_completion(self):
        gateway_mod = load_gateway()
        gateway = gateway_mod.ModelGateway(
            registry=FakeRegistry(),
            routes={"text_reply": {"primary": {"provider_id": "ollama", "model": "llama3"}, "fallbacks": []}},
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            credential_lookup=lambda provider_id: None,
        )
        result = gateway.complete("text_reply", [{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "ollama")

    def test_fallback_after_primary_failure(self):
        def failing_handler(request):
            if request.url.host == "example.test":
                return httpx.Response(500)
            return self.handler(request)

        gateway_mod = load_gateway()
        route = {
            "primary": {"provider_id": "openai", "model": "m1"},
            "fallbacks": [{"provider_id": "ollama", "model": "llama3"}],
        }
        gateway = gateway_mod.ModelGateway(
            registry=FakeRegistry(),
            routes={"text_reply": route},
            http_client=httpx.Client(transport=httpx.MockTransport(failing_handler)),
            credential_lookup=lambda provider_id: None,
        )
        result = gateway.complete("text_reply", [{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "ollama")


class GatewayReplyTests(unittest.TestCase):
    def test_generate_reply_result_prefers_configured_gateway(self):
        import importlib.util
        from pathlib import Path
        reply_path = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_reply.py"
        spec = importlib.util.spec_from_file_location("wechat_ai_reply_gateway_test", reply_path)
        wx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wx)

        class FakeGateway:
            def complete(self, role, messages, json_mode=False):
                self.role = role
                return type("Result", (), {"provider_id": "siliconflow", "model": "Qwen/Qwen2.5-7B-Instruct", "text": "网关回复"})()

        gateway = FakeGateway()
        chat = {"id": "wxid_a", "name": "测试联系人"}
        messages = [{"localId": 1, "chatId": "wxid_a", "senderName": "测试联系人", "content": "你好", "type": 1, "isSelf": False}]
        result = wx.generate_reply_result(chat, messages, {"modelGateway": gateway, "model": "fallback"})
        self.assertEqual(result["route"], "text")
        self.assertEqual(result["reply"], "网关回复")
        self.assertEqual(result["model"], "siliconflow/Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(gateway.role, "text_reply")


class RuntimeGatewayBuilderTests(unittest.TestCase):
    def test_build_runtime_gateway_reads_routes_and_providers(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from wechat_ai_control.runtime_gateway import build_runtime_gateway
        rules = Path(tempfile.mkdtemp()) / "rules.json"
        providers = rules.parent / "providers.json"
        rules.write_text('{"routes":{"text_reply":{"primary":{"provider_id":"p1","model":"m1"},"fallbacks":[]}}}', encoding="utf-8")
        providers.write_text('{"providers":[{"id":"p1","kind":"openai_compatible","name":"P1","base_url":"https://example.test"}]}', encoding="utf-8")
        gateway = build_runtime_gateway(rules, providers)
        self.assertIsNotNone(gateway)
        self.assertEqual(gateway.routes["text_reply"]["primary"]["model"], "m1")


if __name__ == "__main__":
    unittest.main()
