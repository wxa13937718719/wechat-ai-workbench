import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.app import create_app
from wechat_ai_control.config_store import ConfigStore
from wechat_ai_control.models import AppConfig
from wechat_ai_control.wechat_mirror.media import MediaNotDownloaded, MediaNotFound, MediaStream


class FakeProviderRegistry:
    def list_providers(self):
        return [type("P", (), {"id": "siliconflow", "kind": "openai_compatible", "name": "SiliconFlow", "base_url": "https://api.siliconflow.cn", "models": ["Qwen/Qwen2.5-7B-Instruct"], "last_discovered_at": None, "enabled": True, "credential_ref": None})()]


class FakeGateway:
    def __init__(self):
        self.routes = {}

    def complete(self, role, messages, json_mode=False):
        if role == "instruction_parser":
            user_text = messages[-1]["content"]
            if "锁定" in user_text:
                operation = {"op": "lock_chat", "payload": {}, "risk": "high", "summary": "锁定当前联系人"}
            elif "重试" in user_text:
                operation = {"op": "retry_send", "payload": {"text": "重试消息", "retry_token": "retry-1", "client_request_id": "client-1"}, "risk": "high", "summary": "重试发送"}
            elif "当前联系人" in user_text:
                operation = {"op": "set_contact_rule", "payload": {"instruction": "活泼一点"}, "risk": "low", "summary": "更新当前联系人规则"}
            elif "发送" in user_text:
                operation = {"op": "send_message", "payload": {"target_id": "wxid_a", "text": "你好"}, "risk": "high", "summary": "向测试联系人发送消息"}
            else:
                operation = {"op": "set_global_persona", "payload": {"instruction": "活泼一点"}, "risk": "low", "summary": "更新全局人格"}
            text = json.dumps({"operations": [operation]}, ensure_ascii=False)
        else:
            text = "沙盒回复"
        return type("Result", (), {"text": text, "provider_id": "siliconflow", "model": "Qwen/Qwen2.5-7B-Instruct"})()


class ConsoleWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.app = create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            store=self.store,
            provider_registry=FakeProviderRegistry(),
            gateway=FakeGateway(),
            known_chat_ids={"wxid_a"},
            runtime=FakeRuntime(),
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_provider_list_is_exposed(self):
        response = self.client.get("/api/providers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["providers"][0]["id"], "siliconflow")

    def test_command_parse_uses_configured_gateway(self):
        response = self.client.post("/api/commands/parse", json={"text": "以后活泼一点"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "draft")
        self.assertEqual(response.json()["operations"][0]["op"], "set_global_persona")

    def test_sandbox_uses_gateway_without_sending(self):
        response = self.client.post("/api/sandbox/run", json={"chat_id": "wxid_a", "text": "你好"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "沙盒回复")
        self.assertFalse(response.json()["sent"])

    def test_command_preview_has_diff_and_never_exposes_unlock(self):
        response = self.client.post("/api/commands/preview", json={"text": "以后活泼一点", "chatId": "wxid_a"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "draft")
        self.assertFalse(payload["requiresConfirmation"])
        self.assertIn("before", payload["operations"][0])
        self.assertIn("after", payload["operations"][0])
        self.assertNotIn("unlock_chat", response.text)

    def test_high_risk_command_requires_explicit_confirmation(self):
        preview = self.client.post("/api/commands/preview", json={"text": "发送一条消息", "chatId": "wxid_a"}).json()

        denied = self.client.post(f"/api/commands/{preview['commandId']}/apply", json={"confirmHighRisk": False})
        confirmed = self.client.post(f"/api/commands/{preview['commandId']}/apply", json={"confirmHighRisk": True})

        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["error"]["code"], "confirmation_required")
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["status"], "applied")

    def test_preview_resolves_current_chat_without_static_known_ids(self):
        app = create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            store=self.store,
            provider_registry=FakeProviderRegistry(),
            gateway=FakeGateway(),
            runtime=FakeRuntime(),
        )

        response = TestClient(app).post("/api/commands/preview", json={"text": "让当前联系人更活泼", "chatId": "wxid_a"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["operations"][0]["after"]["target_id"], "wxid_a")

    def test_lock_and_retry_commands_execute_after_confirmation(self):
        runtime = FakeRuntime()
        app = create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            store=self.store,
            provider_registry=FakeProviderRegistry(),
            gateway=FakeGateway(),
            runtime=runtime,
        )
        client = TestClient(app)

        lock = client.post("/api/commands/preview", json={"text": "锁定当前联系人", "chatId": "wxid_a"}).json()
        retry = client.post("/api/commands/preview", json={"text": "重试当前消息", "chatId": "wxid_a"}).json()
        lock_result = client.post(f"/api/commands/{lock['commandId']}/apply", json={"confirmHighRisk": True})
        retry_result = client.post(f"/api/commands/{retry['commandId']}/apply", json={"confirmHighRisk": True})

        self.assertEqual(lock_result.status_code, 200)
        self.assertEqual(retry_result.status_code, 200)
        self.assertEqual(runtime.locked, ["wxid_a"])
        self.assertEqual(runtime.retried, [("wxid_a", "重试消息", "client-1", "retry-1")])

    def test_route_update_is_visible_to_running_gateway(self):
        gateway = FakeGateway()
        app = create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            store=self.store,
            provider_registry=FakeProviderRegistry(),
            gateway=gateway,
            runtime=FakeRuntime(),
        )

        response = TestClient(app).post("/api/routes", json={"routes": {
            "instruction_parser": {"primary": {"provider_id": "siliconflow", "model": "parser-v2"}, "fallbacks": []}
        }})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(gateway.routes["instruction_parser"]["primary"]["model"], "parser-v2")


class FakeRuntime:
    def __init__(self):
        self.sent = []
        self.locked = []
        self.retried = []
        self.ai_source = None

    def status(self):
        return {"activeWriter": {"pid": 123}, "unlocked": 2, "pendingChats": 1, "pendingMessages": 3, "paused": False}

    def list_chats(self):
        return [{"id": "wxid_a", "name": "测试联系人", "unlocked": True, "pendingCount": 1}]

    def list_messages(self, chat_id, limit=100):
        return [{"localId": 1, "chatId": chat_id, "content": "你好", "type": 1, "isSelf": False}]

    def list_message_page(self, chat_id, before=None, limit=100):
        return {
            "messages": [{"id": "1", "chatId": chat_id, "display": {"kind": "text", "text": "你好"}}],
            "nextCursor": before,
            "requestedLimit": limit,
        }

    def open_media(self, chat_id, local_id):
        if local_id == 404:
            raise MediaNotFound("missing")
        if local_id == 409:
            raise MediaNotDownloaded("pending")
        return MediaStream(data=b"image-data", mime_type="image/png", etag='"etag"')

    def get_chat(self, chat_id):
        return {"id": chat_id, "name": "测试联系人", "kind": "direct", "members": []}

    def manual_send(self, chat_ref, text, client_request_id=None, retry_token=None):
        self.sent.append((chat_ref, text))
        if retry_token:
            self.retried.append((chat_ref, text, client_request_id, retry_token))
        return {"status": "sent", "sent": True, "message": {"content": text}, "retryToken": None, "clientRequestId": client_request_id, "chat": {"id": "wxid_a", "name": "测试联系人"}, "text": text}

    def mark_handled(self, chat_ref):
        return {"handled": True, "chat": {"id": "wxid_a", "name": "测试联系人"}}

    def lock_chat(self, chat_ref):
        self.locked.append(chat_ref)
        return {"locked": True, "chat": {"id": chat_ref}}

    def set_ai_control(self, chat_ref, action):
        self.ai_source = "manual_granted" if action == "grant" else "manual_revoked"
        return {
            "chat": {"id": chat_ref, "name": "测试联系人"},
            "unlocked": action == "grant",
            "source": self.ai_source,
        }

    def ai_control_status(self, chat_ref):
        return {
            "unlocked": self.ai_source == "manual_granted",
            "source": self.ai_source,
            "manualOverride": self.ai_source,
            "keywordUnlockAllowed": self.ai_source != "manual_revoked",
        }


class RuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.tmp.name))
        self.app = create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            store=self.store,
            provider_registry=FakeProviderRegistry(),
            gateway=FakeGateway(),
            runtime=FakeRuntime(),
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_uses_runtime(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unlocked"], 2)

    def test_chats_and_messages_use_runtime(self):
        chats = self.client.get("/api/chats")
        self.assertEqual(chats.status_code, 200)
        self.assertEqual(chats.json()["chats"][0]["id"], "wxid_a")
        messages = self.client.get("/api/chats/wxid_a/messages")
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(messages.json()["messages"][0]["display"]["text"], "你好")

    def test_message_paging_parameters_are_exposed(self):
        response = self.client.get("/api/chats/wxid_a/messages?before=20&limit=35")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nextCursor"], "20")
        self.assertEqual(response.json()["requestedLimit"], 35)

    def test_media_response_has_private_cache_headers(self):
        response = self.client.get("/api/chats/wxid_a/messages/2/media")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"image-data")
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["cache-control"], "private, max-age=3600")
        self.assertEqual(response.headers["etag"], '"etag"')

    def test_media_errors_are_classified_without_paths(self):
        missing = self.client.get("/api/chats/wxid_a/messages/404/media")
        pending = self.client.get("/api/chats/wxid_a/messages/409/media")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "media_not_found")
        self.assertFalse(missing.json()["error"]["retryable"])
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()["error"]["code"], "media_not_downloaded")
        self.assertTrue(pending.json()["error"]["retryable"])

    def test_chat_detail_is_exposed(self):
        response = self.client.get("/api/chats/wxid_a")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "direct")

    def test_audit_endpoint(self):
        self.store.audit("test", "target", "summary", {})
        response = self.client.get("/api/audit")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["kind"], "test")

    def test_current_chat_control_context_is_aggregated_without_secrets(self):
        self.store.write_rules({
            "rules": [{"id": "contact-rule", "scope": "contact", "target_id": "wxid_a", "instruction": "活泼一点", "reply_mode": "auto"}],
            "routes": {"text_reply": {"provider_id": "siliconflow", "model": "Qwen/Qwen2.5-7B-Instruct"}},
        })
        response = self.client.get("/api/chats/wxid_a/ai-control")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["chatId"], "wxid_a")
        self.assertEqual(payload["replyMode"], "auto")
        self.assertEqual(payload["modelRoute"]["model"], "Qwen/Qwen2.5-7B-Instruct")
        self.assertFalse(payload["unlocked"])
        self.assertNotIn("credential", response.text.lower())
        self.assertNotIn("systemPrompt", response.text)

    def test_lock_endpoint_changes_only_unlock_state(self):
        response = self.client.post("/api/chats/wxid_a/lock")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["locked"])
        self.assertEqual(self.client.get("/api/status").status_code, 200)

    def test_ai_control_endpoint_supports_manual_grant_and_revoke(self):
        granted = self.client.post("/api/chats/wxid_a/ai-control", json={"action": "grant"})
        self.assertEqual(granted.status_code, 200)
        self.assertTrue(granted.json()["unlocked"])
        self.assertEqual(granted.json()["source"], "manual_granted")

        revoked = self.client.post("/api/chats/wxid_a/ai-control", json={"action": "revoke"})
        self.assertEqual(revoked.status_code, 200)
        self.assertFalse(revoked.json()["unlocked"])
        self.assertEqual(revoked.json()["source"], "manual_revoked")

        context = self.client.get("/api/chats/wxid_a/ai-control").json()
        self.assertEqual(context["authorizationSource"], "manual_revoked")
        self.assertFalse(context["keywordUnlockAllowed"])


if __name__ == "__main__":
    unittest.main()
