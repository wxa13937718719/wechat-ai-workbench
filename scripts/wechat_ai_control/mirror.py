from .wechat_mirror.sqlcipher import SqlCipherReader, docker_runner
from .wechat_mirror.contacts import ContactRepository
from .wechat_mirror.media import MediaService
from .wechat_mirror.messages import MessageRepository
from .wechat_mirror.sessions import SessionRepository

_run = docker_runner


class WeChatMirror:
    def __init__(self, reader=None, message_source=None, media_roots=(), media_open_chat=None):
        self.reader = reader or SqlCipherReader()
        self.contacts = ContactRepository(self.reader)
        self.sessions = SessionRepository(self.reader, self.contacts)
        self.messages = MessageRepository(message_source, contacts=self.contacts)
        self.media = MediaService(self.messages, message_source, media_roots=media_roots, open_chat=media_open_chat)

    def _query(self, db_name, sql):
        return self.reader.query(db_name, sql)

    def list_chat_page(self, cursor=None, limit=100, query=None):
        page = self.sessions.list(cursor=cursor, limit=limit, query=query)
        return {"chats": [item.to_dict() for item in page.items], "nextCursor": page.next_cursor}

    def list_chats(self):
        return self.list_chat_page(limit=500)["chats"]

    def get_chat(self, chat_id):
        return self.sessions.get(chat_id).to_dict()

    def list_message_page(self, chat_id, before=None, limit=100):
        page = self.messages.page(chat_id, before=before, limit=limit)
        return {"messages": [item.to_dict() for item in page.items], "nextCursor": page.next_cursor}

    def open_media(self, chat_id, local_id):
        return self.media.open(chat_id, local_id)
