import contextlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from .models import RUNTIME_DEFAULTS, normalize_runtime
except ImportError:  # Support the repository's direct module-loading tests.
    _models_spec = importlib.util.spec_from_file_location(
        "wechat_ai_control_models", Path(__file__).with_name("models.py")
    )
    _models_module = importlib.util.module_from_spec(_models_spec)
    _models_spec.loader.exec_module(_models_module)
    RUNTIME_DEFAULTS = _models_module.RUNTIME_DEFAULTS
    normalize_runtime = _models_module.normalize_runtime


class ConfigStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.control_dir = self.root / "control"
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.rules_path = self.control_dir / "rules.json"
        self.providers_path = self.control_dir / "providers.json"
        self.runtime_path = self.control_dir / "runtime.json"
        self.last_good_path = self.control_dir / "runtime.last-good.json"
        self.audit_path = self.control_dir / "audit.db"
        self._runtime_last_error = None
        self._last_loaded_reload_token = None
        self._runtime_source = "defaults"
        self._init_db()

    def _init_db(self):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, kind TEXT, target TEXT, summary TEXT, payload TEXT, created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, input_text TEXT, operations TEXT, status TEXT, created_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS rule_versions (revision INTEGER PRIMARY KEY, payload TEXT, created_at TEXT)")
            db.commit()

    def _read_json(self, path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _atomic_write(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(path)
        except Exception:
            with contextlib.suppress(FileNotFoundError):
                Path(tmp_name).unlink()
            raise

    def read_rules(self):
        return self._read_json(self.rules_path, {"revision": 0, "rules": [], "routes": {}})

    def _save_rule_version(self, payload):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.execute("INSERT OR REPLACE INTO rule_versions VALUES (?, ?, ?)", (payload.get("revision", 0), json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            db.commit()

    def write_rules(self, payload, expected_revision=None):
        current = self.read_rules()
        if expected_revision is not None and current.get("revision", 0) != expected_revision:
            raise RuntimeError("revision_conflict")
        self._save_rule_version(current)
        payload["revision"] = current.get("revision", 0) + 1
        self._save_rule_version(payload)
        self._atomic_write(self.rules_path, payload)
        return payload

    def rollback_rules(self, revision):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            row = db.execute("SELECT payload FROM rule_versions WHERE revision = ?", (int(revision),)).fetchone()
        if not row:
            if int(revision) == 0:
                restored = {"revision": 0, "rules": [], "routes": {}}
            else:
                raise KeyError(revision)
        else:
            restored = json.loads(row[0])
        return self.write_rules({"rules": restored.get("rules", []), "routes": restored.get("routes", {})})

    def read_providers(self):
        return self._read_json(self.providers_path, {"providers": []})

    def write_providers(self, payload):
        self._atomic_write(self.providers_path, payload)
        return payload

    def ensure_legacy_provider(self, legacy_path, credential_store):
        """Import the old SiliconFlow file without making its key persistent here."""
        legacy_path = Path(legacy_path)
        result = {"id": "siliconflow", "imported": False, "credentialStored": False, "models": []}
        if not legacy_path.exists():
            return result
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return result
        if not isinstance(legacy, dict):
            return result

        raw_providers = self.read_providers().get("providers", [])
        providers = [dict(item) for item in raw_providers if isinstance(item, dict)]
        existing = next((item for item in providers if item.get("id") == "siliconflow"), None)
        created = existing is None
        if existing is None:
            existing = {
                "id": "siliconflow",
                "kind": "siliconflow",
                "name": "SiliconFlow",
                "base_url": "https://api.siliconflow.cn",
                "credential_ref": "siliconflow",
                "models": [],
                "last_discovered_at": None,
                "enabled": True,
            }
            providers.append(existing)
            changed = True
        else:
            changed = False

        # Old configs use the OpenAI-compatible endpoint including /v1;
        # ProviderRegistry appends that path for model discovery itself.
        base_url = str(legacy.get("baseUrl") or "").strip().rstrip("/")
        if base_url.lower().endswith("/v1"):
            base_url = base_url[:-3].rstrip("/")
        if base_url and (created or not existing.get("base_url")):
            existing["base_url"] = base_url
            changed = True

        models = existing.get("models") if isinstance(existing.get("models"), list) else []
        models = [str(model) for model in models if str(model).strip()]
        for candidate in (legacy.get("model"), legacy.get("textModel"), legacy.get("visionModel")):
            if candidate and str(candidate) not in models:
                models.append(str(candidate))
                changed = True
        existing["models"] = models
        for key in ("apiKey", "api_key"):
            # A provider record must never retain a legacy secret, even if a
            # partially migrated file was written by an older console build.
            if key in existing:
                existing.pop(key, None)
                changed = True

        api_key = legacy.get("apiKey")
        if isinstance(api_key, str) and api_key and credential_store is not None:
            try:
                stored = credential_store.set("siliconflow", api_key)
            except Exception:
                stored = False
            result["credentialStored"] = stored is not False
            existing["credential_status"] = "stored" if result["credentialStored"] else "unavailable"
            changed = True
        elif created:
            existing["credential_status"] = "missing"
            changed = True

        if changed:
            self.write_providers({"providers": providers})
        result.update({"imported": changed, "models": models})
        return result

    def _runtime_error(self):
        return {
            "code": "runtime_config_invalid",
            "message": "runtime configuration is invalid",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

    def _load_runtime_file(self, path):
        payload = self._read_json(path, None)
        if payload is None:
            return None
        return normalize_runtime(payload)

    def _remember_runtime(self, snapshot, source):
        value = normalize_runtime(snapshot)
        self._last_loaded_reload_token = value["reloadToken"]
        self._runtime_source = source
        return value

    def read_runtime(self):
        if self.runtime_path.exists():
            try:
                value = self._load_runtime_file(self.runtime_path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                value = None
                self._runtime_last_error = self._runtime_error()
            else:
                self._runtime_last_error = None
            if value is not None:
                self._atomic_write(self.last_good_path, value)
                return self._remember_runtime(value, "runtime")

        if self.last_good_path.exists():
            try:
                value = self._load_runtime_file(self.last_good_path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                value = None
            if value is not None:
                return self._remember_runtime(value, "last-good")

        return self._remember_runtime(RUNTIME_DEFAULTS, "defaults")

    def write_runtime(self, patch, expected_reload_token=None):
        current = self.read_runtime()
        if expected_reload_token is not None and current["reloadToken"] != int(expected_reload_token):
            raise RuntimeError("runtime_revision_conflict")
        allowed = set(RUNTIME_DEFAULTS) - {"reloadToken"}
        merged = dict(current)
        if isinstance(patch, dict):
            merged.update({key: value for key, value in patch.items() if key in allowed})
        merged["reloadToken"] = current["reloadToken"] + 1
        value = normalize_runtime(merged)
        self._atomic_write(self.runtime_path, value)
        self._atomic_write(self.last_good_path, value)
        self._runtime_last_error = None
        return self._remember_runtime(value, "runtime")

    def runtime_status(self):
        value = self.read_runtime()
        return {
            "savedReloadToken": value["reloadToken"],
            "lastLoadedReloadToken": self._last_loaded_reload_token,
            "lastError": self._runtime_last_error,
            "source": self._runtime_source,
        }

    def set_paused(self, paused, reason=""):
        return self.write_runtime({"paused": bool(paused), "reason": reason})

    def bump_reload(self):
        return self.write_runtime({})["reloadToken"]

    def audit(self, kind, target, summary, payload=None):
        event_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.execute("INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?)", (event_id, kind, target, summary, json.dumps(payload or {}, ensure_ascii=False), created_at))
            db.commit()
        return event_id

    def read_audit(self, limit=100):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM audit ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def create_command(self, draft):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.execute("INSERT OR REPLACE INTO commands VALUES (?, ?, ?, ?, ?)", (draft["id"], draft["input_text"], json.dumps(draft.get("operations", []), ensure_ascii=False), draft["status"], draft.get("created_at") or datetime.now(timezone.utc).isoformat()))
            db.commit()
        return draft

    def read_command(self, command_id):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["operations"] = json.loads(result["operations"])
        return result

    def update_command(self, command_id, status):
        with contextlib.closing(sqlite3.connect(self.audit_path)) as db:
            db.execute("UPDATE commands SET status = ? WHERE id = ?", (status, command_id))
            db.commit()

    def resolve_rule(self, chat_id, is_group=False, now=None):
        current = self.read_rules()
        active = []
        for rule in current.get("rules", []):
            if not rule.get("enabled", True):
                continue
            expires_at = rule.get("expires_at")
            if expires_at and now and str(now) > str(expires_at):
                continue
            scope = rule.get("scope")
            if scope == "global" or rule.get("target_id") == chat_id:
                if scope == "group" and not is_group:
                    continue
                active.append(rule)
        rank = {"temporary": 4, "contact": 3, "group": 2, "global": 1}
        active.sort(key=lambda item: (rank.get(item.get("scope"), 0), int(item.get("priority", 0))), reverse=True)
        resolved = {"instruction": "", "reply_mode": "auto", "frequency": {}, "group_policy": {}, "media_policy": {}, "safety_mode": "normal", "source_rule_ids": []}
        for rule in reversed(active):
            resolved["instruction"] = rule.get("instruction") or resolved["instruction"]
            resolved["reply_mode"] = rule.get("reply_mode") or resolved["reply_mode"]
            resolved["frequency"].update(rule.get("frequency") or {})
            resolved["group_policy"].update(rule.get("group_policy") or {})
            resolved["media_policy"].update(rule.get("media_policy") or {})
            resolved["safety_mode"] = rule.get("safety_mode") or resolved["safety_mode"]
            resolved["source_rule_ids"].append(rule.get("id"))
        return resolved
