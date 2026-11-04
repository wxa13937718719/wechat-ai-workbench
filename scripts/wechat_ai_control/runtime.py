import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


AI_DISCLOSURE = "——该内容由AI生成"


class RuntimeBridge:
    def __init__(self, store, wechat, state_path, active_path=None, mirror=None, interaction=None, transfer=None):
        self.store = store
        self.wechat = wechat
        self.state_path = Path(state_path)
        self.active_path = Path(active_path) if active_path else None
        self.mirror = mirror
        self.interaction = interaction
        self.transfer = transfer
        self._send_attempts = {}

    def _load_state(self):
        if not self.state_path.exists():
            return {"unlocked": {}, "lastSeen": {}, "pending": {}}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self, state):
        save_state = getattr(self.wechat, "save_state", None)
        if callable(save_state):
            save_state(self.state_path, state)
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.state_path.name, dir=self.state_path.parent)
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
        Path(tmp_name).replace(self.state_path)

    @staticmethod
    def _fallback_ai_control_status(state, chat_id):
        control = state.get("aiControl", {}).get(chat_id, {})
        control = control if isinstance(control, dict) else {}
        override = control.get("override") if control.get("override") in {"manual_granted", "manual_revoked"} else None
        unlocked_entry = state.get("unlocked", {}).get(chat_id)
        unlocked = isinstance(unlocked_entry, dict) and override != "manual_revoked"
        source = "manual_revoked" if override == "manual_revoked" else (
            (unlocked_entry or {}).get("source") or ("contact_keyword" if unlocked else None)
        )
        return {
            "unlocked": unlocked,
            "source": source,
            "manualOverride": override,
            "keywordUnlockAllowed": override != "manual_revoked",
        }

    def ai_control_status(self, chat_ref):
        chat_id = chat_ref.get("id") if isinstance(chat_ref, dict) else str(chat_ref)
        state = self._load_state()
        helper = getattr(self.wechat, "ai_control_status", None)
        if callable(helper):
            return helper(state, chat_id)
        return self._fallback_ai_control_status(state, chat_id)

    def set_ai_control(self, chat_ref, action):
        chat = self.wechat.resolve_chat(chat_ref)
        state = self._load_state()
        if action == "grant":
            helper = getattr(self.wechat, "grant_ai_access", None)
            if callable(helper):
                helper(state, chat)
            else:
                state.setdefault("aiControl", {})[chat["id"]] = {
                    "override": "manual_granted",
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                }
                state.setdefault("unlocked", {})[chat["id"]] = {
                    "name": chat.get("name") or chat["id"],
                    "unlockedAt": datetime.now(timezone.utc).isoformat(),
                    "source": "manual_granted",
                }
        elif action == "revoke":
            helper = getattr(self.wechat, "revoke_ai_access", None)
            if callable(helper):
                helper(state, chat)
            else:
                state.setdefault("aiControl", {})[chat["id"]] = {
                    "override": "manual_revoked",
                    "updatedAt": datetime.now(timezone.utc).isoformat(),
                }
                state.setdefault("unlocked", {}).pop(chat["id"], None)
        else:
            raise ValueError("action must be grant or revoke")
        self._save_state(state)
        result = self.ai_control_status(chat["id"])
        self.store.audit(
            f"chat.ai.{action}",
            chat["id"],
            "manually granted AI replies" if action == "grant" else "manually revoked AI replies",
            {"source": "manual"},
        )
        return {"chat": chat, **result}

    def _active_writer_payload(self):
        if not self.active_path or not self.active_path.exists():
            return None
        try:
            value = json.loads(self.active_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def config_status(self):
        saved_status = self.store.runtime_status()
        saved = {
            "reloadToken": saved_status["savedReloadToken"],
            "source": saved_status["source"],
            "lastError": saved_status["lastError"],
        }
        active = self._active_writer_payload() or {}
        effective = {
            "reloadToken": active.get("controlConfigRevision"),
            "source": active.get("controlConfigSource", "unknown"),
            "loadedAt": active.get("controlConfigLoadedAt"),
            "lastError": active.get("controlConfigError"),
            "interactionMode": active.get("interactionMode"),
            "interactionEnforcement": active.get("interactionEnforcement"),
            "idleTimeoutSeconds": active.get("idleTimeoutSeconds"),
        }
        if effective["lastError"] or saved["lastError"]:
            health = "warning"
        elif effective["reloadToken"] is None:
            health = "pending_reload"
        elif effective["reloadToken"] == saved["reloadToken"]:
            health = "healthy"
        else:
            health = "pending_reload"
        return {"saved": saved, "effective": effective, "health": health}

    def status(self):
        active = None
        active = self._active_writer_payload()
        state = self._load_state()
        pending = state.get("pending", {})
        payload = {
            "activeWriter": active,
            "unlocked": len(state.get("unlocked", {})),
            "pendingChats": len(pending),
            "pendingMessages": sum(len(items) for items in pending.values()),
            "paused": self.store.read_runtime().get("paused", False),
            "runtimeConfig": self.config_status(),
        }
        payload["interaction"] = self.interaction_status()
        payload["transfer"] = self.transfer_status()
        return payload

    def transfer_status(self):
        if self.transfer is None:
            return {
                "transactionId": None,
                "source": "unknown",
                "stage": "idle",
                "active": False,
                "itemCount": 0,
                "startedAt": None,
                "finishedAt": None,
                "outcome": None,
                "errorCode": "transfer_coordinator_unconfigured",
                "enforcement": "observe_only",
            }
        payload = self.transfer.status()
        payload["enforcement"] = "observe_only"
        return payload

    def interaction_status(self):
        if self.interaction is None:
            return {
                "state": "PAUSED_UNKNOWN",
                "reason": "interaction_arbiter_unconfigured",
                "canAutomate": False,
                "enforcement": "observe_only",
                "lastHumanActionAt": None,
                "idleDeadlineAt": None,
                "countdownDeadlineAt": None,
                "idleRemainingSeconds": None,
                "countdownRemainingSeconds": None,
                "transactionId": None,
                "leaseId": None,
                "leaseChatId": None,
                "window": {
                    "status": "unknown",
                    "windowId": None,
                    "title": "",
                    "chatTitle": "",
                    "bounds": None,
                    "isForeground": False,
                    "loggedIn": None,
                    "automationReady": False,
                    "reason": "interaction_arbiter_unconfigured",
                    "observedAt": None,
                },
            }
        snapshot = self.interaction.observe()
        if hasattr(snapshot, "to_dict"):
            payload = snapshot.to_dict()
            payload["enforcement"] = "observe_only"
            return payload
        return {
            "state": "PAUSED_UNKNOWN",
            "reason": "interaction_snapshot_invalid",
            "canAutomate": False,
            "enforcement": "observe_only",
        }

    def _enrich_chats(self, chats, state):
        for chat in chats:
            chat["unlocked"] = self.wechat.is_unlocked(state, chat["id"])
            chat["pendingCount"] = len(state.get("pending", {}).get(chat["id"], []))
        return chats

    def list_chat_page(self, cursor=None, limit=100, query=None):
        state = self._load_state()
        if self.mirror is not None:
            try:
                if hasattr(self.mirror, "list_chat_page"):
                    page = self.mirror.list_chat_page(cursor=cursor, limit=limit, query=query)
                else:
                    page = {"chats": self.mirror.list_chats(), "nextCursor": None}
                page["chats"] = self._enrich_chats(page.get("chats", []), state)
                return page
            except Exception:
                pass
        chats = self.wechat.list_chats(limit=1000)
        contacts = []
        if hasattr(self.wechat, "list_contacts"):
            contacts = self.wechat.list_contacts(limit=5000) or []
        individual_ids = {item.get("username") for item in contacts if item.get("contactType") == "individual"}
        visible = []
        visible_ids = set()
        for chat in chats:
            chat_id = str(chat.get("id") or "")
            if chat_id == "brandsessionholder" or chat_id.startswith("gh_"):
                continue
            if chat_id.startswith("@placeholder") or str(chat.get("name") or "").startswith("@placeholder"):
                continue
            if not chat.get("isGroup") and chat_id not in individual_ids and chat_id != "filehelper":
                continue
            chat["source"] = "api-fallback"
            visible.append(chat)
            visible_ids.add(chat_id)
        for contact in contacts:
            contact_id = str(contact.get("username") or contact.get("id") or "")
            if not contact_id or contact_id in visible_ids or contact.get("contactType") not in (None, "individual"):
                continue
            visible.append({
                "id": contact_id,
                "name": str(contact.get("remark") or contact.get("nickName") or contact.get("name") or contact_id),
                "kind": "direct",
                "isGroup": False,
                "updatedAt": 0,
                "lastActivityAt": "",
                "lastMessagePreview": "",
                "unreadCount": 0,
                "avatar": str(contact.get("smallHeadUrl") or contact.get("avatar") or ""),
                "source": "contact-fallback",
            })
            visible_ids.add(contact_id)
        if query:
            needle = str(query).casefold()
            visible = [chat for chat in visible if needle in str(chat.get("name") or "").casefold() or needle in str(chat.get("id") or "").casefold()]
        offset = max(0, int(cursor or 0))
        size = min(max(1, int(limit)), 500)
        page = visible[offset:offset + size]
        next_offset = offset + len(page)
        return {
            "chats": self._enrich_chats(page, state),
            "nextCursor": str(next_offset) if next_offset < len(visible) else None,
        }

    def list_chats(self, cursor=None, limit=100, query=None):
        return self.list_chat_page(cursor=cursor, limit=limit, query=query)["chats"]

    def get_chat(self, chat_id):
        if self.mirror is not None and hasattr(self.mirror, "get_chat"):
            try:
                detail = self.mirror.get_chat(chat_id)
                state = self._load_state()
                detail["unlocked"] = self.wechat.is_unlocked(state, chat_id)
                detail["pendingCount"] = len(state.get("pending", {}).get(chat_id, []))
                return detail
            except Exception:
                pass
        chat = self.wechat.resolve_chat(chat_id)
        return {**chat, "kind": "group" if chat.get("isGroup") else "direct", "members": [], "source": "api-fallback"}

    def list_messages(self, chat_id, limit=100):
        return self.list_message_page(chat_id, limit=limit)["messages"]

    def list_message_page(self, chat_id, before=None, limit=100):
        if self.mirror is not None and hasattr(self.mirror, "list_message_page"):
            try:
                return self.mirror.list_message_page(chat_id, before=before, limit=limit)
            except (KeyError, ValueError):
                raise
            except Exception:
                pass
        messages = self.wechat.list_messages(chat_id, limit=limit)
        return {"messages": messages, "nextCursor": None}

    def open_media(self, chat_id, local_id):
        if self.mirror is None or not hasattr(self.mirror, "open_media"):
            raise LookupError("media mirror is unavailable")
        return self.mirror.open_media(chat_id, local_id)

    def capabilities(self):
        open_media = bool(
            (self.mirror is not None and callable(getattr(self.mirror, "open_media", None)))
            or callable(getattr(self.wechat, "get_message_media", None))
        )
        return {
            "sendText": callable(getattr(self.wechat, "send_message", None)),
            "sendImage": callable(getattr(self.wechat, "send_image", None)),
            "sendFile": callable(getattr(self.wechat, "send_file", None)),
            "sendSticker": callable(getattr(self.wechat, "send_sticker", None)),
            "playVoice": open_media,
            "openMedia": open_media,
        }

    def snapshot(self):
        page = self.list_chat_page(limit=500)
        runtime = self.store.read_runtime()
        active = None
        if self.active_path and self.active_path.exists():
            try:
                active = json.loads(self.active_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                active = None
        return {
            "chats": page.get("chats", []),
            "daemonRevision": {
                "reloadToken": int(runtime.get("reloadToken", 0)),
                "paused": bool(runtime.get("paused", False)),
                "pid": active.get("pid") if isinstance(active, dict) else None,
                "heartbeatAt": active.get("heartbeatAt") if isinstance(active, dict) else None,
            },
        }

    def _verified_text_message(self, chat_id, text, before_ids):
        try:
            messages = self.wechat.list_messages(chat_id, limit=100) or []
        except Exception:
            return None
        for message in reversed(messages):
            message_id = str(message.get("localId") or message.get("id") or "")
            if message_id in before_ids:
                continue
            if not bool(message.get("isSelf") or message.get("is_self")):
                continue
            content = str(message.get("content") or "")
            if content not in {text, f"{text}\n\n{AI_DISCLOSURE}", f"{text}{AI_DISCLOSURE}"}:
                continue
            timestamp = message.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = int(datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp())
                except ValueError:
                    timestamp = 0
            return {
                "id": message_id,
                "localId": message.get("localId"),
                "chatId": chat_id,
                "type": 1,
                "direction": "outgoing",
                "timestamp": int(timestamp or 0),
                "sender": {"id": str(message.get("sender") or "self"), "name": str(message.get("senderName") or "我"), "avatar": ""},
                "display": {"kind": "text", "text": text},
                "media": [],
                "status": "sent",
                "content": text,
            }
        return None

    def _complete_send(self, attempt, message):
        attempt["status"] = "sent"
        attempt["message"] = message
        attempt["retryToken"] = None
        attempt["retryable"] = False
        if not attempt.get("audited"):
            self.store.audit(
                "manual.send",
                attempt["chat"]["id"],
                "sent manual message",
                {"clientRequestId": attempt["clientRequestId"], "messageId": message.get("id")},
            )
            attempt["audited"] = True
        state = self._load_state()
        if self.wechat.is_unlocked(state, attempt["chat"]["id"]):
            self.wechat.acknowledge_pending(state, attempt["chat"]["id"])
            self._save_state(state)
        return self._public_send_result(attempt)

    @staticmethod
    def _public_send_result(attempt):
        return {key: value for key, value in attempt.items() if key not in {"beforeIds", "audited"}}

    def manual_send(self, chat_ref, text, client_request_id=None, retry_token=None):
        chat = self.wechat.resolve_chat(chat_ref)
        request_id = str(client_request_id or uuid.uuid4().hex)
        previous = self._send_attempts.get(request_id)
        if previous is not None:
            if previous["chat"]["id"] != chat["id"] or previous["text"] != text:
                raise ValueError("clientRequestId already belongs to another send")
            if previous["status"] == "sent":
                return self._public_send_result(previous)
            message = self._verified_text_message(chat["id"], text, previous["beforeIds"])
            if message:
                return self._complete_send(previous, message)
            if not retry_token or retry_token != previous.get("retryToken"):
                return self._public_send_result(previous)
            before_ids = previous["beforeIds"]
        else:
            try:
                before = self.wechat.list_messages(chat["id"], limit=100) or []
                before_ids = {str(message.get("localId") or message.get("id") or "") for message in before}
            except Exception:
                before_ids = set()
            previous = {
                "status": "pending",
                "sent": False,
                "message": None,
                "retryToken": None,
                "retryable": False,
                "clientRequestId": request_id,
                "chat": chat,
                "text": text,
                "beforeIds": before_ids,
                "audited": False,
            }
            self._send_attempts[request_id] = previous
        code = self.wechat.send_message(chat, text, do_send=True)
        message = self._verified_text_message(chat["id"], text, before_ids) if code == 0 else None
        status = "sent" if message else ("unknown" if code == 0 else "failed")
        next_retry_token = None if status == "sent" else str(retry_token or uuid.uuid4().hex)
        previous.update({
            "status": status,
            "sent": status == "sent",
            "message": message,
            "retryToken": next_retry_token,
            "retryable": status != "sent",
        })
        if status == "sent":
            return self._complete_send(previous, message)
        return self._public_send_result(previous)

    def lock_chat(self, chat_ref):
        result = self.set_ai_control(chat_ref, "revoke")
        return {"locked": True, **result}

    def mark_handled(self, chat_ref):
        chat = self.wechat.resolve_chat(chat_ref)
        state = self._load_state()
        if self.wechat.is_unlocked(state, chat["id"]):
            self.wechat.acknowledge_pending(state, chat["id"])
            self._save_state(state)
        return {"handled": True, "chat": chat}

    def pause(self, reason=""):
        return self.store.set_paused(True, reason)

    def resume(self):
        return self.store.set_paused(False, "")

    def bump_reload(self):
        return self.store.bump_reload()

    def run_sandbox(self, chat_id, text, gateway, is_group=False):
        resolved = self.store.resolve_rule(chat_id, is_group=is_group)
        messages = [
            {"role": "system", "content": resolved.get("instruction") or ""},
            {"role": "user", "content": text},
        ]
        result = gateway.complete("text_reply", messages)
        return {
            "reply": result.text,
            "route": {"provider_id": result.provider_id, "model": result.model},
            "resolvedRule": resolved,
            "sent": False,
        }
