import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from wechat_ai_control.wechat_mirror.models import (  # noqa: E402
    Capabilities,
    ChatDetail,
    ChatSummary,
    MediaRef,
    MessageView,
    SenderView,
)


class WeChatMirrorModelTests(unittest.TestCase):
    def test_chat_summary_uses_json_safe_camel_case_contract(self):
        value = ChatSummary(
            id="group@chatroom",
            name="测试群",
            kind="group",
            updated_at=1,
            unread_count=2,
            last_sender_name="成员甲",
        )

        payload = value.to_dict()

        self.assertEqual(payload["kind"], "group")
        self.assertEqual(payload["unreadCount"], 2)
        self.assertEqual(payload["lastSenderName"], "成员甲")
        self.assertEqual(payload["draft"], "")
        self.assertEqual(payload["avatar"], "")
        json.dumps(payload, ensure_ascii=False)

    def test_chat_detail_serializes_members_and_capabilities(self):
        detail = ChatDetail(
            summary=ChatSummary(id="group@chatroom", name="测试群", kind="group", updated_at=1),
            members=(SenderView(id="wxid_member", name="成员甲", avatar="https://example.test/a.jpg"),),
            capabilities=Capabilities(send_text=True, send_image=False),
        )

        payload = detail.to_dict()

        self.assertEqual(payload["id"], "group@chatroom")
        self.assertEqual(payload["members"][0]["name"], "成员甲")
        self.assertTrue(payload["capabilities"]["sendText"])
        self.assertFalse(payload["capabilities"]["sendImage"])

    def test_unknown_message_keeps_type_for_diagnostics(self):
        value = MessageView(
            id="9",
            chat_id="wxid_friend",
            type=9999,
            direction="incoming",
            timestamp=1,
        )

        payload = value.to_dict()

        self.assertEqual(payload["display"]["kind"], "unsupported")
        self.assertEqual(payload["type"], 9999)
        self.assertEqual(payload["chatId"], "wxid_friend")
        self.assertEqual(payload["media"], [])

    def test_message_contract_omits_raw_database_values(self):
        value = MessageView(
            id="10",
            chat_id="wxid_friend",
            type=3,
            direction="outgoing",
            timestamp=2,
            sender=SenderView(id="self", name="我"),
            display={"kind": "image", "alt": "图片"},
            media=(MediaRef(id="10:image", kind="image", mime_type="image/jpeg"),),
        )

        payload = value.to_dict()

        self.assertNotIn("raw", payload)
        self.assertNotIn("path", payload["media"][0])
        self.assertEqual(payload["sender"]["name"], "我")
        self.assertEqual(payload["media"][0]["mimeType"], "image/jpeg")


if __name__ == "__main__":
    unittest.main()
