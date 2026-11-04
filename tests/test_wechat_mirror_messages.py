import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_ai_control.wechat_mirror.messages import MessageRepository  # noqa: E402
from wechat_ai_control.wechat_mirror.contacts import ContactRepository  # noqa: E402


class FixtureMessageSource:
    def __init__(self):
        path = ROOT / "tests" / "fixtures" / "wechat" / "message_rows.json"
        self.rows = json.loads(path.read_text(encoding="utf-8"))
        self.rows.extend([
            {
                "localId": 7,
                "chatId": "wxid_friend",
                "sender": "wxid_friend",
                "senderName": "朋友",
                "type": 49,
                "content": "<appmsg><type>5</type><title>课程主页</title><des>课程说明</des><url>https://example.test/course</url></appmsg>",
                "timestamp": "2026-09-20T00:00:07+00:00",
                "isSelf": False,
            },
            {
                "localId": 8,
                "chatId": "wxid_friend",
                "sender": "wxid_friend",
                "senderName": "朋友",
                "type": 49,
                "content": "<appmsg><type>57</type><title>收到</title><refermsg><displayname>我</displayname><content>原消息</content></refermsg></appmsg>",
                "timestamp": "2026-09-20T00:00:08+00:00",
                "isSelf": False,
            },
            {
                "localId": 9,
                "chatId": "wxid_friend",
                "sender": "wxid_friend",
                "senderName": "朋友",
                "type": 49,
                "content": "<appmsg>",
                "timestamp": "2026-09-20T00:00:09+00:00",
                "isSelf": False,
            },
        ])

    def list_messages(self, chat_id, limit=5000):
        return [row for row in self.rows if row["chatId"] == chat_id][-limit:]


class FixtureContacts:
    def get(self, chat_id):
        if chat_id == "wxid_friend":
            return type("Contact", (), {"avatar": "https://example.test/friend.jpg", "name": "朋友"})()
        return None

    def members(self, _chat_id):
        return ()


class MessageRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = MessageRepository(FixtureMessageSource())

    def test_sender_avatar_is_resolved_from_contact_metadata(self):
        repo = MessageRepository(FixtureMessageSource(), contacts=FixtureContacts())
        message = repo.page("wxid_friend", limit=1).items[0]

        self.assertEqual(message.sender.avatar, "https://example.test/friend.jpg")

    def test_ai_disclosure_is_hidden_from_message_body(self):
        source = FixtureMessageSource()
        source.rows.append({
            "localId": 99,
            "chatId": "wxid_friend",
            "sender": "self",
            "senderName": "我",
            "type": 1,
            "content": "回复内容\n\n——该内容由AI生成",
            "timestamp": "2026-09-20T00:01:00+00:00",
            "isSelf": True,
        })
        message = MessageRepository(source).page("wxid_friend", limit=1).items[0]

        self.assertEqual(message.display["text"], "回复内容")

    def test_group_message_uses_real_sender(self):
        msg = self.repo.page("group@chatroom", before=None, limit=20).items[0]

        self.assertEqual(msg.sender.name, "成员甲")
        self.assertEqual(msg.direction, "incoming")

    def test_before_cursor_has_no_overlap(self):
        newest = self.repo.page("wxid_friend", before=None, limit=2)
        older = self.repo.page("wxid_friend", before=newest.next_cursor, limit=2)

        self.assertTrue(set(x.id for x in newest.items).isdisjoint(x.id for x in older.items))
        self.assertEqual([item.id for item in newest.items], ["8", "9"])
        self.assertEqual([item.id for item in older.items], ["5", "7"])

    def test_common_message_types_are_structured(self):
        messages = self.repo.page("wxid_friend", before=None, limit=20).items
        by_id = {message.id: message for message in messages}

        self.assertEqual(by_id["1"].display, {"kind": "text", "text": "文本消息"})
        self.assertEqual(by_id["2"].display["kind"], "image")
        self.assertEqual(by_id["3"].display["kind"], "sticker")
        self.assertEqual(by_id["4"].display["kind"], "voice")
        self.assertEqual(by_id["5"].display["kind"], "file")
        self.assertEqual(by_id["7"].display["kind"], "link")
        self.assertEqual(by_id["8"].display["kind"], "quote")

    def test_system_and_malformed_messages_have_safe_displays(self):
        system = self.repo.page("group@chatroom", before=None, limit=20).items[0]
        malformed = self.repo.page("wxid_friend", before=None, limit=1).items[0]

        self.assertEqual(system.display, {"kind": "system", "text": "系统消息"})
        self.assertEqual(malformed.display["kind"], "unsupported")
        self.assertEqual(malformed.display["diagnosticCode"], "malformed_app_message")
        self.assertNotIn("raw", malformed.display)


if __name__ == "__main__":
    unittest.main()
