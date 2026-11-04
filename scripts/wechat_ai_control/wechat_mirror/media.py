import base64
import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


class MediaNotFound(LookupError):
    pass


class MediaNotDownloaded(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaStream:
    data: bytes
    mime_type: str
    etag: str
    cache_control: str = "private, max-age=3600"
    file_name: str = ""


def _etag(data: bytes) -> str:
    return f'"{hashlib.sha256(data).hexdigest()}"'


class MediaService:
    def __init__(self, messages, source, media_roots=(), open_chat=None):
        self.messages = messages
        self.source = source
        self.media_roots = tuple(Path(root).resolve() for root in media_roots)
        self.open_chat = open_chat

    def _known_ref(self, chat_id, local_id):
        ref = self.messages.media_ref(chat_id, local_id)
        if not ref:
            raise MediaNotFound("unknown media message")
        return ref

    def open(self, chat_id, local_id):
        ref = self._known_ref(chat_id, local_id)
        if self.source is None or not hasattr(self.source, "get_message_media"):
            raise MediaNotDownloaded("media is not downloaded")
        payload = self.source.get_message_media(chat_id, int(local_id))
        if (not isinstance(payload, dict) or not payload.get("data")) and callable(self.open_chat):
            # agent-wechat downloads thumbnails when a chat is opened. Keep
            # unread state intact and retry once; never write WeChat DB files.
            try:
                self.open_chat(chat_id)
                payload = self.source.get_message_media(chat_id, int(local_id))
            except Exception:
                # A failed download should remain a typed 409 in the API,
                # rather than exposing a transport or UI error to the user.
                payload = None
        if not isinstance(payload, dict) or not payload.get("data"):
            raise MediaNotDownloaded("media is not downloaded")
        try:
            data = base64.b64decode(payload["data"], validate=True)
        except (ValueError, TypeError) as exc:
            raise MediaNotDownloaded("media payload is invalid") from exc
        if not data:
            raise MediaNotDownloaded("media is empty")
        mime_type = str(payload.get("mimeType") or payload.get("mime_type") or ref.get("mimeType") or "application/octet-stream")
        return MediaStream(data=data, mime_type=mime_type, etag=_etag(data), file_name=str(ref.get("fileName") or ""))

    def open_local(self, chat_id, local_id, relative_path):
        ref = self._known_ref(chat_id, local_id)
        raw = str(relative_path or "")
        windows = PureWindowsPath(raw)
        posix = PurePosixPath(raw)
        if not raw or windows.is_absolute() or windows.drive or posix.is_absolute() or ".." in windows.parts or ".." in posix.parts:
            raise MediaNotFound("invalid media path")
        for root in self.media_roots:
            candidate = (root / Path(raw)).resolve()
            if not candidate.is_relative_to(root):
                continue
            if candidate.is_file():
                data = candidate.read_bytes()
                mime_type = mimetypes.guess_type(candidate.name)[0] or str(ref.get("mimeType") or "application/octet-stream")
                return MediaStream(data=data, mime_type=mime_type, etag=_etag(data), file_name=candidate.name)
        raise MediaNotFound("media file not found")
