from datetime import datetime
from xml.etree import ElementTree

from .models import MediaRef, MessageView, SenderView
from .sessions import Page


MESSAGE_FETCH_LIMIT = 5000
AI_DISCLOSURE = "——该内容由AI生成"


def _display_text(content: str) -> str:
    text = str(content or "")
    suffix = f"\n\n{AI_DISCLOSURE}"
    if text.endswith(suffix):
        return text[:-len(suffix)]
    if text.endswith(AI_DISCLOSURE):
        return text[:-len(AI_DISCLOSURE)].rstrip()
    return text


def _timestamp(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return 0


def _text(root, path, default="") -> str:
    node = root.find(path)
    return str(node.text or "") if node is not None else default


def _app_message(content: str, local_id: int):
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, TypeError):
        return {"kind": "unsupported", "diagnosticCode": "malformed_app_message"}, ()

    app_type = _text(root, "type")
    title = _text(root, "title")
    description = _text(root, "des")
    url = _text(root, "url")
    if app_type in {"33", "36"} or root.find("weappinfo") is not None:
        weapp = root.find("weappinfo")
        weapp_title = _text(weapp, "pagepath") if weapp is not None else ""
        weapp_owner = _text(weapp, "username") if weapp is not None else ""
        return {
            "kind": "mini_program",
            "title": title or weapp_title,
            "description": description or weapp_owner,
            "url": url,
            "source": _text(root, "appinfo/appname"),
        }, ()
    if app_type == "57" or root.find("refermsg") is not None:
        return {
            "kind": "quote",
            "text": title,
            "quotedSender": _text(root, "refermsg/displayname"),
            "quotedText": _text(root, "refermsg/content"),
        }, ()
    if app_type == "5" or url:
        return {
            "kind": "link",
            "title": title,
            "description": description,
            "url": url,
            "source": _text(root, "appinfo/appname"),
        }, ()

    file_name = title or _text(root, "appattach/fileext") or "文件"
    size_text = _text(root, "appattach/totallen", "0")
    try:
        size = int(size_text or 0)
    except ValueError:
        size = 0
    media = MediaRef(id=f"{local_id}:file", kind="file", file_name=file_name, size=size)
    return {"kind": "file", "fileName": file_name, "size": size}, (media,)


def _display(raw: dict, local_id: int, message_type: int):
    content = str(raw.get("content") or "")
    if message_type == 1:
        return {"kind": "text", "text": _display_text(content)}, ()
    if message_type == 3:
        media = MediaRef(id=f"{local_id}:image", kind="image", mime_type="image/jpeg")
        return {"kind": "image", "alt": "图片"}, (media,)
    if message_type == 47:
        sticker_url = content.strip() if content.strip().startswith(("http://", "https://")) else ""
        media = MediaRef(id=f"{local_id}:sticker", kind="sticker", mime_type="image/gif", url=sticker_url, animated=True)
        return {"kind": "sticker", "alt": "表情包"}, (media,)
    if message_type == 34:
        duration = int(raw.get("durationMs") or raw.get("duration") or 0)
        media = MediaRef(id=f"{local_id}:voice", kind="voice", mime_type="audio/mpeg", duration_ms=duration)
        return {"kind": "voice", "durationMs": duration}, (media,)
    if message_type == 49:
        return _app_message(content, local_id)
    if message_type in (10000, 10002):
        return {"kind": "system", "text": content}, ()
    return {"kind": "unsupported", "diagnosticCode": f"unsupported_message_type_{message_type}"}, ()


class MessageRepository:
    def __init__(self, source, contacts=None):
        self.source = source
        self.contacts = contacts

    def _raw_messages(self, chat_id):
        if self.source is None or not hasattr(self.source, "list_messages"):
            return []
        return list(self.source.list_messages(chat_id, limit=MESSAGE_FETCH_LIMIT) or [])

    def _normalize(self, chat_id, raw):
        local_id = int(raw.get("localId") or raw.get("local_id") or 0)
        message_type = int(raw.get("type") or 0)
        is_self = bool(raw.get("isSelf") or raw.get("is_self"))
        sender_id = str(raw.get("sender") or ("self" if is_self else chat_id))
        contact = self.contacts.get(sender_id) if self.contacts and not is_self else None
        sender_name = str(raw.get("senderName") or raw.get("sender_name") or (contact.name if contact else ("我" if is_self else sender_id)))
        sender_avatar = str(raw.get("senderAvatar") or raw.get("sender_avatar") or (contact.avatar if contact else ""))
        display, media = _display(raw, local_id, message_type)
        return MessageView(
            id=str(local_id),
            chat_id=chat_id,
            type=message_type,
            subtype=int(raw.get("subType") or raw.get("sub_type") or 0),
            direction="outgoing" if is_self else "incoming",
            timestamp=_timestamp(raw.get("timestamp")),
            sender=SenderView(id=sender_id, name=sender_name, avatar=sender_avatar),
            display=display,
            media=media,
            status=str(raw.get("status") or ""),
        )

    def page(self, chat_id, before=None, limit=100):
        size = min(max(1, int(limit)), 500)
        rows = sorted(
            self._raw_messages(chat_id),
            key=lambda row: (int(row.get("localId") or row.get("local_id") or 0), str(row.get("timestamp") or "")),
        )
        if before is not None:
            try:
                boundary = int(before)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid message cursor") from exc
            rows = [row for row in rows if int(row.get("localId") or row.get("local_id") or 0) < boundary]
        selected = rows[-size:]
        items = tuple(self._normalize(chat_id, row) for row in selected)
        next_cursor = None
        if selected and len(rows) > len(selected):
            next_cursor = str(int(selected[0].get("localId") or selected[0].get("local_id") or 0))
        return Page(items, next_cursor)

    def media_ref(self, chat_id, local_id):
        wanted = str(int(local_id))
        for row in self._raw_messages(chat_id):
            if str(int(row.get("localId") or row.get("local_id") or 0)) != wanted:
                continue
            message = self._normalize(chat_id, row)
            return message.media[0].to_dict() if message.media else None
        return None
