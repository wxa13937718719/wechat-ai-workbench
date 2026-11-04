from dataclasses import dataclass

from .models import SenderView


@dataclass(frozen=True)
class ContactRecord:
    id: int
    username: str
    name: str
    avatar: str
    muted: bool


class ContactRepository:
    def __init__(self, reader):
        self.reader = reader
        self._loaded = False
        self._contacts = {}
        self._official_ids = set()
        self._group_ids = set()
        self._members = {}
        self._session_titles = {}

    def _load(self):
        if self._loaded:
            return
        contacts = self.reader.query(
            "contact.db",
            "SELECT id, username, local_type, alias, verify_flag, remark, nick_name, small_head_url, chat_room_notify FROM contact",
        )
        for row in contacts:
            username = str(row.get("username") or "")
            if not username:
                continue
            self._contacts[username] = ContactRecord(
                id=int(row.get("id") or 0),
                username=username,
                name=str(row.get("remark") or row.get("nick_name") or username),
                avatar=str(row.get("small_head_url") or ""),
                muted=bool(row.get("chat_room_notify") or False),
            )

        self._official_ids = {
            str(row.get("username") or "")
            for row in self.reader.query("contact.db", "SELECT username FROM biz_info")
            if row.get("username")
        }
        groups = self.reader.query("contact.db", "SELECT id, username, owner FROM chat_room")
        self._group_ids = {str(row.get("username") or "") for row in groups if row.get("username")}
        member_rows = self.reader.query(
            "contact.db",
            "SELECT cr.username AS room_username, c.username, c.nick_name, c.remark, c.small_head_url "
            "FROM chatroom_member cm JOIN chat_room cr ON cr.id = cm.room_id "
            "JOIN contact c ON c.id = cm.member_id ORDER BY cm.rowid",
        )
        for row in member_rows:
            room_id = str(row.get("room_username") or "")
            member_id = str(row.get("username") or "")
            if not room_id or not member_id:
                continue
            self._members.setdefault(room_id, []).append(SenderView(
                id=member_id,
                name=str(row.get("remark") or row.get("nick_name") or member_id),
                avatar=str(row.get("small_head_url") or ""),
            ))
        titles = self.reader.query("session.db", "SELECT username, session_title FROM SessionNoContactInfoTable")
        self._session_titles = {
            str(row.get("username") or ""): str(row.get("session_title") or "")
            for row in titles
            if row.get("username")
        }
        self._loaded = True

    @property
    def official_ids(self):
        self._load()
        return set(self._official_ids)

    @property
    def group_ids(self):
        self._load()
        return set(self._group_ids)

    def get(self, chat_id):
        self._load()
        return self._contacts.get(chat_id)

    def records(self):
        self._load()
        return tuple(self._contacts.values())

    def members(self, chat_id):
        self._load()
        return tuple(self._members.get(chat_id, ()))

    def session_title(self, chat_id):
        self._load()
        return self._session_titles.get(chat_id, "")
