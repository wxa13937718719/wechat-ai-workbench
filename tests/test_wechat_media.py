import base64
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_ai_control.wechat_mirror.media import (  # noqa: E402
    MediaNotDownloaded,
    MediaNotFound,
    MediaService,
)


class StubMessages:
    def media_ref(self, chat_id, local_id):
        if (chat_id, int(local_id)) == ("wxid_friend", 2):
            return {"id": "2:image", "kind": "image", "mimeType": "image/png"}
        if (chat_id, int(local_id)) == ("wxid_friend", 3):
            return {"id": "3:sticker", "kind": "sticker", "mimeType": "image/gif"}
        return None


class StubMediaSource:
    def __init__(self, payload):
        self.payload = payload

    def get_message_media(self, chat_id, local_id):
        return self.payload


class RetryMediaSource(StubMediaSource):
    def __init__(self):
        super().__init__({"type": "image", "format": "jpg"})
        self.opened = 0

    def open_chat(self, _chat_id):
        self.opened += 1

    def get_message_media(self, chat_id, local_id):
        if self.opened:
            return {"type": "image", "mimeType": "image/png", "data": base64.b64encode(b"downloaded").decode("ascii")}
        return super().get_message_media(chat_id, local_id)


class MediaServiceTests(unittest.TestCase):
    def test_known_media_returns_private_stream_with_etag(self):
        payload = {"type": "image", "mimeType": "image/png", "data": base64.b64encode(b"png-data").decode("ascii")}
        stream = MediaService(StubMessages(), StubMediaSource(payload)).open("wxid_friend", 2)

        self.assertEqual(stream.data, b"png-data")
        self.assertEqual(stream.mime_type, "image/png")
        self.assertEqual(stream.cache_control, "private, max-age=3600")
        self.assertTrue(stream.etag.startswith('"') and stream.etag.endswith('"'))

    def test_unknown_or_not_downloaded_media_is_classified(self):
        service = MediaService(StubMessages(), StubMediaSource({"type": "pending"}))

        with self.assertRaises(MediaNotFound):
            service.open("wxid_friend", 999)
        with self.assertRaises(MediaNotDownloaded):
            service.open("wxid_friend", 2)

    def test_media_open_retries_after_chat_download_hook(self):
        source = RetryMediaSource()
        stream = MediaService(StubMessages(), source, open_chat=source.open_chat).open("wxid_friend", 2)

        self.assertEqual(stream.data, b"downloaded")
        self.assertEqual(source.opened, 1)

    def test_local_media_rejects_escape_drive_and_unc_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MediaService(StubMessages(), None, media_roots=[temp_dir])
            for candidate in ("../secret.png", "D:\\secret.png", "\\\\server\\share\\secret.png"):
                with self.subTest(candidate=candidate), self.assertRaises(MediaNotFound):
                    service.open_local("wxid_friend", 2, candidate)

    def test_local_media_reads_only_inside_configured_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "image.png").write_bytes(b"local-png")
            service = MediaService(StubMessages(), None, media_roots=[root])

            stream = service.open_local("wxid_friend", 2, "image.png")

        self.assertEqual(stream.data, b"local-png")
        self.assertEqual(stream.mime_type, "image/png")


if __name__ == "__main__":
    unittest.main()
