import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

RUNTIME_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_control" / "runtime.py"
STORE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wechat_ai_control" / "config_store.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeWeChat:
    def __init__(self):
        self.sent = []
        self.messages = [{"localId": 1, "chatId": "wxid_friend", "content": "你好", "type": 1, "isSelf": False}]

    def resolve_chat(self, value):
        return {"id": "wxid_friend", "name": "测试联系人"}

    def send_message(self, chat, text, do_send=True):
        self.sent.append((chat["id"], text, do_send))
        self.messages.append({
            "localId": max(item["localId"] for item in self.messages) + 1,
            "chatId": chat["id"],
            "content": text,
            "type": 1,
            "isSelf": True,
            "sender": "self",
            "senderName": "我",
            "timestamp": "2026-09-20T10:00:00+08:00",
        })
        return 0

    def is_unlocked(self, state, chat_id):
        return chat_id in state.get("unlocked", {})

    def acknowledge_pending(self, state, chat_id):
        state.setdefault("pending", {}).pop(chat_id, None)

    def pending_messages(self, state, chat_id):
        return state.get("pending", {}).get(chat_id, [])

    def list_chats(self, limit=1000):
        return [{"id": "wxid_friend", "name": "测试联系人", "isGroup": False}]

    def list_messages(self, chat_id, limit=100):
        return self.messages[-limit:]

    def load_state(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def save_state(self, path, state):
        Path(path).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def get_message_media(self, chat_id, local_id):
        return {"type": "image", "data": ""}


class FallbackWeChat(FakeWeChat):
    def list_chats(self, limit=1000):
        return [{"id": "wxid_news", "name": "校园新闻网同学", "isGroup": False}]

    def list_contacts(self, limit=5000):
        return [{"username": "wxid_news", "contactType": "individual", "alias": "friend"}]


class MessageMirror:
    def list_message_page(self, chat_id, before=None, limit=100):
        return {"messages": [{"id": "2", "chatId": chat_id}], "nextCursor": before, "limit": limit}

    def open_media(self, chat_id, local_id):
        return (chat_id, local_id)


class FailedWeChat(FakeWeChat):
    def send_message(self, chat, text, do_send=True):
        self.sent.append((chat["id"], text, do_send))
        return 7


class AmbiguousWeChat(FakeWeChat):
    def send_message(self, chat, text, do_send=True):
        self.sent.append((chat["id"], text, do_send))
        return 0


class DelayedAmbiguousWeChat(AmbiguousWeChat):
    def reveal_sent_message(self, text):
        self.messages.append({
            "localId": 2,
            "chatId": "wxid_friend",
            "content": text,
            "type": 1,
            "isSelf": True,
            "sender": "self",
            "senderName": "我",
            "timestamp": "2026-09-20T10:00:00+08:00",
        })


class RuntimeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = load_module("wechat_ai_control_config_store", STORE_PATH).ConfigStore(self.root)
        self.wechat = FakeWeChat()
        self.state_path = self.root / "state.json"
        self.state_path.write_text(json.dumps({"unlocked": {}, "lastSeen": {}, "pending": {}}), encoding="utf-8")
        self.bridge = load_module("wechat_ai_control_runtime", RUNTIME_PATH).RuntimeBridge(
            store=self.store,
            wechat=self.wechat,
            state_path=self.state_path,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_send_to_locked_chat_does_not_unlock_or_clear_pending(self):
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["pending"]["wxid_friend"] = [{"localId": 2}]
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        result = self.bridge.manual_send("测试联系人", "手动回复")
        self.assertEqual(result["status"], "sent")
        loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertNotIn("wxid_friend", loaded["unlocked"])
        self.assertEqual(len(loaded["pending"]["wxid_friend"]), 1)

    def test_manual_send_to_unlocked_chat_clears_current_batch(self):
        state = {"unlocked": {"wxid_friend": {"name": "测试联系人"}}, "lastSeen": {}, "pending": {"wxid_friend": [{"localId": 2}]}}
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        result = self.bridge.manual_send("测试联系人", "手动回复")
        self.assertEqual(result["status"], "sent")
        loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["pending"].get("wxid_friend", []), [])

    def test_pause_and_reload_round_trip(self):
        self.bridge.pause("testing")
        self.assertTrue(self.store.read_runtime()["paused"])
        first = self.bridge.bump_reload()
        second = self.bridge.bump_reload()
        self.assertEqual(second, first + 1)

    def test_api_fallback_keeps_normal_contact_with_news_in_name(self):
        bridge = load_module("wechat_ai_control_runtime_fallback", RUNTIME_PATH).RuntimeBridge(
            store=self.store,
            wechat=FallbackWeChat(),
            state_path=self.state_path,
        )

        chats = bridge.list_chats()

        self.assertEqual([chat["id"] for chat in chats], ["wxid_news"])
        self.assertEqual(chats[0]["source"], "api-fallback")

    def test_message_page_and_media_use_mirror_when_available(self):
        bridge = load_module("wechat_ai_control_runtime_messages", RUNTIME_PATH).RuntimeBridge(
            store=self.store,
            wechat=self.wechat,
            state_path=self.state_path,
            mirror=MessageMirror(),
        )

        page = bridge.list_message_page("wxid_friend", before="9", limit=25)

        self.assertEqual(page["messages"][0]["id"], "2")
        self.assertEqual(page["nextCursor"], "9")
        self.assertEqual(page["limit"], 25)
        self.assertEqual(bridge.open_media("wxid_friend", 2), ("wxid_friend", 2))

    def test_capabilities_reflect_real_adapter_methods(self):
        capabilities = self.bridge.capabilities()

        self.assertTrue(capabilities["sendText"])
        self.assertTrue(capabilities["openMedia"])
        self.assertTrue(capabilities["playVoice"])
        self.assertFalse(capabilities["sendImage"])
        self.assertFalse(capabilities["sendFile"])

    def test_send_returns_verified_message(self):
        result = self.bridge.manual_send("wxid_friend", "新的手动消息", client_request_id="client-1")

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["message"]["content"], "新的手动消息")
        self.assertEqual(result["message"]["direction"], "outgoing")
        self.assertEqual(result["clientRequestId"], "client-1")
        self.assertIsNone(result["retryToken"])

    def test_explicit_send_failure_has_retry_token(self):
        bridge = load_module("wechat_ai_control_runtime_failed_send", RUNTIME_PATH).RuntimeBridge(
            store=self.store,
            wechat=FailedWeChat(),
            state_path=self.state_path,
        )

        result = bridge.manual_send("wxid_friend", "失败消息", client_request_id="client-2")

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["message"])
        self.assertTrue(result["retryToken"])

    def test_ambiguous_send_requires_recent_message_recheck(self):
        bridge = load_module("wechat_ai_control_runtime_ambiguous_send", RUNTIME_PATH).RuntimeBridge(
            store=self.store,
            wechat=AmbiguousWeChat(),
            state_path=self.state_path,
        )

        result = bridge.manual_send("wxid_friend", "待确认消息", client_request_id="client-3")

        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["retryToken"])
        self.assertTrue(result["retryable"])

    def test_retry_reconciles_delayed_success_without_duplicate_send(self):
        wechat = DelayedAmbiguousWeChat()
        bridge = load_module("wechat_ai_control_runtime_delayed_send", RUNTIME_PATH).RuntimeBridge(
            store=self.store,
            wechat=wechat,
            state_path=self.state_path,
        )
        first = bridge.manual_send("wxid_friend", "延迟消息", client_request_id="client-delayed")
        wechat.reveal_sent_message("延迟消息")

        retried = bridge.manual_send(
            "wxid_friend",
            "延迟消息",
            client_request_id="client-delayed",
            retry_token=first["retryToken"],
        )

        self.assertEqual(retried["status"], "sent")
        self.assertEqual(len(wechat.sent), 1)

    def test_successful_manual_send_is_idempotent_and_audited(self):
        first = self.bridge.manual_send("wxid_friend", "只发一次", client_request_id="client-once")
        second = self.bridge.manual_send("wxid_friend", "只发一次", client_request_id="client-once")

        self.assertEqual(first["message"]["id"], second["message"]["id"])
        self.assertEqual(len(self.wechat.sent), 1)
        events = self.store.read_audit()
        self.assertEqual(events[0]["kind"], "manual.send")
        self.assertNotIn("只发一次", events[0]["payload"])

    def test_lock_chat_removes_only_unlock_permission(self):
        state = {
            "unlocked": {"wxid_friend": {"name": "测试联系人"}},
            "lastSeen": {"wxid_friend": 10},
            "pending": {"wxid_friend": [{"localId": 11}]},
        }
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

        result = self.bridge.lock_chat("wxid_friend")

        loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertTrue(result["locked"])
        self.assertNotIn("wxid_friend", loaded["unlocked"])
        self.assertEqual(loaded["pending"]["wxid_friend"][0]["localId"], 11)

    def test_manual_ai_control_grant_and_revoke_are_audited(self):
        granted = self.bridge.set_ai_control("wxid_friend", "grant")
        self.assertTrue(granted["unlocked"])
        self.assertEqual(granted["source"], "manual_granted")

        revoked = self.bridge.set_ai_control("wxid_friend", "revoke")
        self.assertFalse(revoked["unlocked"])
        self.assertEqual(revoked["source"], "manual_revoked")
        self.assertEqual(
            [event["kind"] for event in self.store.read_audit(limit=2)],
            ["chat.ai.revoke", "chat.ai.grant"],
        )


if __name__ == "__main__":
    unittest.main()
