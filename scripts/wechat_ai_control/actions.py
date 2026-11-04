import contextlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class ActionCenter:
    def __init__(self, store):
        self.store = store
        with contextlib.closing(sqlite3.connect(self.store.audit_path)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, kind TEXT, target TEXT, summary TEXT, payload TEXT, status TEXT, created_at TEXT)")
            db.commit()

    def create(self, kind, target, summary, payload=None):
        action_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        with contextlib.closing(sqlite3.connect(self.store.audit_path)) as db:
            db.execute("INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, ?)", (action_id, kind, target, summary, json.dumps(payload or {}, ensure_ascii=False), "open", created_at))
            db.commit()
        return {"id": action_id, "kind": kind, "target": target, "summary": summary, "status": "open"}

    def _set_status(self, action_id, status):
        with contextlib.closing(sqlite3.connect(self.store.audit_path)) as db:
            db.execute("UPDATE actions SET status = ? WHERE id = ?", (status, action_id))
            db.commit()
        return self.get(action_id)

    def get(self, action_id):
        with contextlib.closing(sqlite3.connect(self.store.audit_path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def list(self):
        with contextlib.closing(sqlite3.connect(self.store.audit_path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM actions ORDER BY created_at DESC LIMIT 200").fetchall()
        return [dict(row) for row in rows]

    def retry(self, action_id):
        return self._set_status(action_id, "retrying")

    def dismiss(self, action_id, reason):
        self.store.audit("action.dismiss", action_id, reason, {})
        return self._set_status(action_id, "dismissed")

    def require_confirmation(self, action_id):
        return self._set_status(action_id, "awaiting_confirmation")

    def confirm(self, action_id):
        self.store.audit("action.confirm", action_id, "confirmed high-risk action", {})
        return self._set_status(action_id, "resolved")
