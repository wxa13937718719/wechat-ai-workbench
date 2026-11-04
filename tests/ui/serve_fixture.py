import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from wechat_ai_control.app import create_app  # noqa: E402
from wechat_ai_control.models import AppConfig  # noqa: E402


class FixtureRuntime:
    def status(self):
        return {"activeWriter": None, "unlocked": 0, "pendingChats": 0, "pendingMessages": 0, "paused": False}

    def list_chat_page(self, **_kwargs):
        return {"chats": [], "nextCursor": None}

    def list_message_page(self, _chat_id, **_kwargs):
        return {"messages": [], "nextCursor": None}

    def get_chat(self, chat_id):
        return {"id": chat_id, "name": chat_id, "kind": "direct", "members": []}

    def capabilities(self):
        return {name: False for name in ("sendText", "sendImage", "sendFile", "sendSticker", "playVoice", "openMedia")}

    def snapshot(self):
        return {"chats": [], "daemonRevision": {}}


app = create_app(AppConfig(state_dir=ROOT / ".ui-test-state"), runtime=FixtureRuntime())


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8876, log_level="warning")
