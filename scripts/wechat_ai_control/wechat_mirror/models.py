from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SenderView:
    id: str
    name: str
    avatar: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "avatar": self.avatar}


@dataclass(frozen=True)
class MediaRef:
    id: str
    kind: str
    mime_type: str = ""
    url: str = ""
    file_name: str = ""
    size: int = 0
    width: int = 0
    height: int = 0
    duration_ms: int = 0
    available: bool = True
    animated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "mimeType": self.mime_type,
            "url": self.url,
            "fileName": self.file_name,
            "size": self.size,
            "width": self.width,
            "height": self.height,
            "durationMs": self.duration_ms,
            "available": self.available,
            "animated": self.animated,
        }


@dataclass(frozen=True)
class Capabilities:
    send_text: bool = False
    send_image: bool = False
    send_file: bool = False
    send_sticker: bool = False
    play_voice: bool = False
    open_media: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "sendText": self.send_text,
            "sendImage": self.send_image,
            "sendFile": self.send_file,
            "sendSticker": self.send_sticker,
            "playVoice": self.play_voice,
            "openMedia": self.open_media,
        }


@dataclass(frozen=True)
class ChatSummary:
    id: str
    name: str
    kind: str
    updated_at: int
    avatar: str = ""
    unread_count: int = 0
    last_message_preview: str = ""
    last_sender_name: str = ""
    draft: str = ""
    pinned: bool = False
    muted: bool = False
    source: str = "mirror"
    avatar_members: tuple[str, ...] = ()
    last_message_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        activity = datetime.fromtimestamp(self.updated_at, tz=timezone.utc).isoformat() if self.updated_at else ""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "updatedAt": self.updated_at,
            "avatar": self.avatar,
            "unreadCount": self.unread_count,
            "lastMessagePreview": self.last_message_preview,
            "lastSenderName": self.last_sender_name,
            "draft": self.draft,
            "pinned": self.pinned,
            "muted": self.muted,
            "source": self.source,
            "avatarMembers": list(self.avatar_members),
            "isGroup": self.kind == "group",
            "lastActivityAt": activity,
            "lastMessageId": self.last_message_id,
        }


@dataclass(frozen=True)
class ChatDetail:
    summary: ChatSummary
    members: tuple[SenderView, ...] = ()
    capabilities: Capabilities = field(default_factory=Capabilities)

    @property
    def draft(self) -> str:
        return self.summary.draft

    @property
    def unread_count(self) -> int:
        return self.summary.unread_count

    def to_dict(self) -> dict[str, Any]:
        payload = self.summary.to_dict()
        payload.update({
            "members": [member.to_dict() for member in self.members],
            "capabilities": self.capabilities.to_dict(),
        })
        return payload


@dataclass(frozen=True)
class MessageView:
    id: str
    chat_id: str
    type: int
    direction: str
    timestamp: int
    subtype: int = 0
    sender: SenderView | None = None
    display: dict[str, Any] | None = None
    media: tuple[MediaRef, ...] = ()
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        display = dict(self.display) if self.display is not None else {
            "kind": "unsupported",
            "diagnosticCode": f"unsupported_message_type_{self.type}",
        }
        return {
            "id": self.id,
            "chatId": self.chat_id,
            "type": self.type,
            "subtype": self.subtype,
            "direction": self.direction,
            "timestamp": self.timestamp,
            "sender": self.sender.to_dict() if self.sender else None,
            "display": display,
            "media": [item.to_dict() for item in self.media],
            "status": self.status,
        }
