import hashlib
import json
import threading
import time


def _chat_fingerprint(chat):
    return (
        str(chat.get("id") or ""),
        int(chat.get("updatedAt") or 0),
        int(chat.get("unreadCount") or 0),
        str(chat.get("lastMessageId") or ""),
    )


def _snapshot_digest(snapshot):
    tracked = {
        "chats": [_chat_fingerprint(chat) for chat in snapshot.get("chats", [])],
        "daemonRevision": snapshot.get("daemonRevision") or {},
    }
    encoded = json.dumps(tracked, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class UpdateFeed:
    def __init__(self, snapshot_provider, timeout=2.0, interval=0.1, clock=None, sleep=None):
        self.snapshot_provider = snapshot_provider
        self.timeout = max(0.0, float(timeout))
        self.interval = max(0.01, float(interval))
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._snapshot = None
        self._digest = ""
        self._cursor = 0
        self._events = []

    def _capture(self):
        current = json.loads(json.dumps(self.snapshot_provider(), ensure_ascii=False))
        digest = _snapshot_digest(current)
        if digest == self._digest:
            return False
        previous = self._snapshot or {"chats": [], "daemonRevision": {}}
        old_chats = {str(chat.get("id") or ""): chat for chat in previous.get("chats", [])}
        new_chats = {str(chat.get("id") or ""): chat for chat in current.get("chats", [])}
        old_order = list(old_chats)
        new_order = list(new_chats)
        changed = [
            chat for chat_id, chat in new_chats.items()
            if _chat_fingerprint(chat) != _chat_fingerprint(old_chats.get(chat_id, {}))
        ]
        message_ids = {}
        for chat in changed:
            chat_id = str(chat.get("id") or "")
            new_id = str(chat.get("lastMessageId") or "")
            old_id = str(old_chats.get(chat_id, {}).get("lastMessageId") or "")
            if new_id and new_id != old_id:
                message_ids[chat_id] = [new_id]
        daemon_revision = current.get("daemonRevision") or {}
        daemon_changed = daemon_revision != (previous.get("daemonRevision") or {})
        self._cursor += 1
        event = {
            "cursor": self._cursor,
            "chats": changed,
            "chatOrder": new_order if new_order != old_order else [],
            "messageIds": message_ids,
            "daemonRevision": daemon_revision if daemon_changed else None,
        }
        self._events.append(event)
        self._events = self._events[-256:]
        self._snapshot = current
        self._digest = digest
        return True

    def _events_after(self, since):
        events = [event for event in self._events if event["cursor"] > since]
        chats = {}
        message_ids = {}
        chat_order = []
        daemon_revision = None
        for event in events:
            chats.update({str(chat.get("id") or ""): chat for chat in event["chats"]})
            for chat_id, ids in event["messageIds"].items():
                target = message_ids.setdefault(chat_id, [])
                target.extend(item for item in ids if item not in target)
            if event["chatOrder"]:
                chat_order = event["chatOrder"]
            if event["daemonRevision"] is not None:
                daemon_revision = event["daemonRevision"]
        return {
            "cursor": self._cursor,
            "changed": bool(events),
            "chats": list(chats.values()),
            "chatOrder": chat_order,
            "messageIds": message_ids,
            "daemonRevision": daemon_revision,
        }

    def poll(self, since=0):
        try:
            requested = max(0, int(since or 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid update cursor") from exc
        deadline = self.clock() + self.timeout
        while True:
            with self._lock:
                self._capture()
                if self._cursor > requested:
                    return self._events_after(requested)
                cursor = self._cursor
            if self.clock() >= deadline:
                return {
                    "cursor": cursor,
                    "changed": False,
                    "chats": [],
                    "chatOrder": [],
                    "messageIds": {},
                    "daemonRevision": None,
                }
            self.sleep(min(self.interval, max(0.0, deadline - self.clock())))
