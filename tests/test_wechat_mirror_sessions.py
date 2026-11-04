import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_ai_control.wechat_mirror.contacts import ContactRepository  # noqa: E402
from wechat_ai_control.wechat_mirror.sessions import SessionRepository  # noqa: E402


class FixtureReader:
    def __init__(self):
        fixture_dir = ROOT / "tests" / "fixtures" / "wechat"
        self.sessions = json.loads((fixture_dir / "session_rows.json").read_text(encoding="utf-8"))
        self.sessions.append({
            "username": "wxid_news_friend",
            "type": 1,
            "unread_count": 0,
            "summary": "课程资料",
            "draft": "",
            "status": 0,
            "sort_timestamp": 40,
            "last_timestamp": 40,
            "last_msg_locald_id": 3,
            "last_msg_type": 1,
            "last_sender_display_name": "校园新闻网同学",
            "is_hidden": 0,
        })
        self.contacts = json.loads((fixture_dir / "contact_rows.json").read_text(encoding="utf-8"))

    def query(self, db_name, sql, params=()):
        if "FROM SessionTable" in sql:
            return self.sessions
        if "FROM biz_info" in sql:
            return [{"username": "gh_official"}]
        if "FROM chat_room_info_detail" in sql:
            return []
        if "FROM chat_room" in sql and "JOIN" not in sql:
            return [{"id": 20, "username": "group@chatroom", "owner": "wxid_owner"}]
        if "FROM chatroom_member" in sql:
            return [
                {"room_username": "group@chatroom", "username": "wxid_member", "nick_name": "成员甲", "remark": "", "small_head_url": "https://example.test/member.jpg"},
                {"room_username": "group@chatroom", "username": "wxid_owner", "nick_name": "群主", "remark": "", "small_head_url": "https://example.test/owner.jpg"},
            ]
        if "FROM contact" in sql:
            return self.contacts
        if "FROM SessionNoContactInfoTable" in sql:
            return []
        raise AssertionError(f"unexpected query: {db_name} {sql}")


class SessionRepositoryTests(unittest.TestCase):
    def setUp(self):
        reader = FixtureReader()
        self.repo = SessionRepository(reader, ContactRepository(reader))

    def test_official_and_fold_containers_are_excluded(self):
        ids = [item.id for item in self.repo.list(limit=100).items]

        self.assertNotIn("gh_official", ids)
        self.assertNotIn("brandsessionholder", ids)
        self.assertNotIn("@placeholder_foldgroup", ids)

    def test_normal_contact_named_news_is_not_filtered(self):
        ids = [item.id for item in self.repo.list(limit=100).items]

        self.assertIn("wxid_news_friend", ids)

    def test_draft_unread_and_last_sender_are_preserved(self):
        chat = self.repo.get("group@chatroom")

        self.assertEqual(chat.draft, "未发送草稿")
        self.assertEqual(chat.unread_count, 2)
        self.assertEqual(chat.summary.last_sender_name, "成员甲")

    def test_group_detail_contains_real_members_and_avatar_candidates(self):
        chat = self.repo.get("group@chatroom")

        self.assertEqual([member.name for member in chat.members], ["成员甲", "群主"])
        self.assertEqual(len(chat.summary.avatar_members), 2)

    def test_list_supports_search_and_cursor_pagination(self):
        first = self.repo.list(limit=2)
        second = self.repo.list(cursor=first.next_cursor, limit=2)
        searched = self.repo.list(query="新闻网", limit=20)

        self.assertEqual(len(first.items), 2)
        self.assertTrue(set(item.id for item in first.items).isdisjoint(item.id for item in second.items))
        self.assertEqual([item.id for item in searched.items], ["wxid_news_friend"])

    def test_contact_without_session_is_searchable(self):
        self.repo.contacts._contacts["wxid_no_session"] = type(
            "Contact", (), {
                "id": 99,
                "username": "wxid_no_session",
                "name": "还没发过消息的人",
                "avatar": "https://example.test/no-session.jpg",
                "muted": False,
            }
        )()

        searched = self.repo.list(query="还没发过", limit=20)

        self.assertEqual([item.id for item in searched.items], ["wxid_no_session"])
        self.assertEqual(searched.items[0].updated_at, 0)


if __name__ == "__main__":
    unittest.main()
