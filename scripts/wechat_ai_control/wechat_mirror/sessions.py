from dataclasses import dataclass

from .models import Capabilities, ChatDetail, ChatSummary


CONTAINER_IDS = {"brandsessionholder", "@placeholder_foldgroup"}


@dataclass(frozen=True)
class Page:
    items: tuple
    next_cursor: str | None = None

    def to_dict(self):
        return {
            "items": [item.to_dict() for item in self.items],
            "nextCursor": self.next_cursor,
        }


class SessionRepository:
    def __init__(self, reader, contacts):
        self.reader = reader
        self.contacts = contacts

    def _summaries(self):
        rows = self.reader.query(
            "session.db",
            "SELECT username, type, unread_count, is_hidden, summary, draft, status, last_timestamp, "
            "sort_timestamp, last_msg_locald_id, last_msg_type, last_msg_sub_type, "
            "last_msg_sender, last_sender_display_name FROM SessionTable ORDER BY sort_timestamp DESC",
        )
        summaries = {}
        official_ids = self.contacts.official_ids
        group_ids = self.contacts.group_ids
        for row in rows:
            chat_id = str(row.get("username") or "")
            if not chat_id or bool(row.get("is_hidden")):
                continue
            if chat_id in CONTAINER_IDS or chat_id in official_ids:
                continue
            if chat_id == "filehelper":
                kind = "file_helper"
            elif chat_id in group_ids or chat_id.endswith("@chatroom"):
                kind = "group"
            else:
                kind = "direct"
            contact = self.contacts.get(chat_id)
            members = self.contacts.members(chat_id) if kind == "group" else ()
            updated_at = int(row.get("sort_timestamp") or row.get("last_timestamp") or 0)
            last_timestamp = int(row.get("last_timestamp") or 0)
            summaries[chat_id] = ChatSummary(
                id=chat_id,
                name=(contact.name if contact else self.contacts.session_title(chat_id) or chat_id),
                kind=kind,
                updated_at=updated_at,
                avatar=contact.avatar if contact else "",
                unread_count=int(row.get("unread_count") or 0),
                last_message_preview=str(row.get("summary") or ""),
                last_sender_name=str(row.get("last_sender_display_name") or ""),
                draft=str(row.get("draft") or ""),
                pinned=bool(last_timestamp and updated_at - last_timestamp > 86400),
                muted=contact.muted if contact else False,
                avatar_members=tuple(member.avatar for member in members if member.avatar)[:9],
                last_message_id=str(row.get("last_msg_locald_id") or ""),
            )

        # Contacts without a session are still searchable and can be opened
        # before the first message is sent.
        for contact in self.contacts.records():
            chat_id = contact.username
            if not chat_id or chat_id in summaries:
                continue
            if chat_id in CONTAINER_IDS or chat_id in official_ids or chat_id in group_ids:
                continue
            if chat_id == "filehelper":
                kind = "file_helper"
            else:
                kind = "direct"
            summaries[chat_id] = ChatSummary(
                id=chat_id,
                name=contact.name or chat_id,
                kind=kind,
                updated_at=0,
                avatar=contact.avatar,
                muted=contact.muted,
            )
        return sorted(summaries.values(), key=lambda item: (-item.updated_at, item.name.casefold(), item.id))

    def list(self, cursor=None, limit=100, query=None):
        items = self._summaries()
        if query:
            needle = str(query).casefold()
            items = [item for item in items if needle in item.name.casefold() or needle in item.id.casefold()]
        offset = max(0, int(cursor or 0))
        size = min(max(1, int(limit)), 500)
        selected = tuple(items[offset:offset + size])
        next_offset = offset + len(selected)
        next_cursor = str(next_offset) if next_offset < len(items) else None
        return Page(selected, next_cursor)

    def get(self, chat_id):
        summary = next((item for item in self._summaries() if item.id == chat_id), None)
        if summary is None:
            raise KeyError(chat_id)
        capabilities = Capabilities(send_text=True, open_media=True)
        return ChatDetail(summary=summary, members=self.contacts.members(chat_id), capabilities=capabilities)
