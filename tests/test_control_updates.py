import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_ai_control.app import create_app  # noqa: E402
from wechat_ai_control.models import AppConfig  # noqa: E402
from wechat_ai_control.updates import UpdateFeed  # noqa: E402
from wechat_ai_control.wechat_mirror.sqlcipher import DatabaseUnavailable  # noqa: E402


class MutableSnapshots:
    def __init__(self):
        self.value = {
            "chats": [
                {"id": "a", "updatedAt": 20, "unreadCount": 1, "lastMessageId": "10"},
                {"id": "b", "updatedAt": 10, "unreadCount": 0, "lastMessageId": "5"},
            ],
            "daemonRevision": {"reloadToken": 1, "paused": False},
        }

    def __call__(self):
        return self.value


class UpdateFeedTests(unittest.TestCase):
    def setUp(self):
        self.snapshots = MutableSnapshots()
        self.feed = UpdateFeed(self.snapshots, timeout=0)

    def test_updates_returns_monotonic_cursor_and_no_change_payload(self):
        first = self.feed.poll(0)
        second = self.feed.poll(first["cursor"])

        self.assertGreaterEqual(second["cursor"], first["cursor"])
        self.assertEqual(second["chats"], [])
        self.assertEqual(second["messageIds"], {})
        self.assertFalse(second["changed"])

    def test_new_message_returns_id_without_body(self):
        first = self.feed.poll(0)
        self.snapshots.value["chats"][0].update({"updatedAt": 21, "lastMessageId": "11"})

        update = self.feed.poll(first["cursor"])

        self.assertEqual(update["messageIds"], {"a": ["11"]})
        self.assertEqual([chat["id"] for chat in update["chats"]], ["a"])
        self.assertNotIn("content", update["chats"][0])

    def test_reordered_sessions_return_new_order(self):
        first = self.feed.poll(0)
        self.snapshots.value["chats"].reverse()

        update = self.feed.poll(first["cursor"])

        self.assertEqual(update["chatOrder"], ["b", "a"])
        self.assertTrue(update["changed"])


class FailingRuntime:
    def list_chat_page(self, **_kwargs):
        raise DatabaseUnavailable("secret key must not leak")

    def capabilities(self):
        return {"sendText": True, "sendImage": False, "sendFile": False, "sendSticker": False, "playVoice": True, "openMedia": True}

    def snapshot(self):
        return {"chats": [], "daemonRevision": {}}


class UpdateApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = FailingRuntime()
        self.client = TestClient(create_app(
            AppConfig(state_dir=Path(self.tmp.name)),
            runtime=self.runtime,
            update_feed=UpdateFeed(self.runtime.snapshot, timeout=0),
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def test_database_failure_has_stable_error_code(self):
        response = self.client.get("/api/chats")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "wechat_database_unavailable")
        self.assertTrue(response.json()["error"]["retryable"])
        self.assertNotIn("secret", response.text)

    def test_capabilities_and_update_endpoints_are_exposed(self):
        capabilities = self.client.get("/api/capabilities")
        updates = self.client.get("/api/updates?since=0")

        self.assertEqual(capabilities.status_code, 200)
        self.assertTrue(capabilities.json()["sendText"])
        self.assertFalse(capabilities.json()["sendImage"])
        self.assertEqual(updates.status_code, 200)
        self.assertIn("cursor", updates.json())


if __name__ == "__main__":
    unittest.main()
