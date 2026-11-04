#!/usr/bin/env python3
"""Standalone WeChat AI reply daemon."""

import argparse
import json
import logging
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wechat_ai_reply as wechat_core
from wechat_ai_paths import state_dir, state_paths
try:
    from wechat_ai_control.runtime_gateway import build_runtime_gateway
    from wechat_ai_control.models import normalize_runtime
except Exception:
    build_runtime_gateway = None
    normalize_runtime = lambda payload: dict(payload or {})
try:
    from wechat_ai_control.interaction import InteractionArbiter
    from wechat_ai_control.send_guard import SendGuard
    from wechat_ai_control.vm_activity import VmActivitySource
    from wechat_ai_control.vm_window import VmWindowAdapter
except Exception:
    InteractionArbiter = None
    SendGuard = None
    VmActivitySource = None
    VmWindowAdapter = None

DUPLICATE_WINDOW_SECONDS = 600

DEFAULT_CONFIG = {
    "pollIntervalSeconds": 30,
    "autoStartDocker": True,
    "autoStartContainer": True,
    "dockerStartTimeoutSeconds": 180,
    "containerStartTimeoutSeconds": 120,
    "componentCheckIntervalSeconds": 10,
    "qrLoginTimeoutSeconds": 300,
    "qrMaxRetries": 3,
    "openQrAutomatically": True,
    "errorBackoffSeconds": 30,
    "maxBackoffSeconds": 300,
    "unlockKeyword": "解锁AI",
    "testChatIds": [],
    "groupChatIds": [],
    "groupChatNames": {},
    "groupReplyProbability": 0.1,
    "groupMinIntervalSeconds": 1800,
    "groupMentionMinIntervalSeconds": 300,
    "groupActiveWindowSeconds": 300,
    "groupActiveReplyProbability": 0.4,
    "groupActiveMinIntervalSeconds": 120,
    "groupActiveMentionMinIntervalSeconds": 30,
    "groupMaxReplyChars": 120,
    "groupMentionPatterns": ["@AI助手", "有没有AI"],
    "groupReplyInstruction": "这是已授权的群聊，回复要简短、友好、自然，不要刷屏，不要编造事实或身份。",
    "textModel": "Qwen/Qwen2.5-7B-Instruct",
    "visionModel": "Qwen/Qwen3-VL-8B-Instruct",
    "maxVisionImages": 10,
    "maxReplyChars": 500,
    "perChatMinIntervalSeconds": 8,
    "perChatHourlyLimit": 30,
    "logLevel": "INFO",
    "daemonMode": "shadow",
}
DEFAULT_CONFIG.update(state_paths(state_dir()))


def expand_path(value):
    return os.path.expandvars(os.path.expanduser(str(value)))


def load_config(path):
    path = Path(path).expanduser().resolve()
    config = {**DEFAULT_CONFIG, **state_paths(path.parent)}
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8-sig")))
    for key in ("qrImagePath", "activeWriterPath", "stopFlagPath", "heartbeatPath", "logPath", "statePath", "siliconflowConfigPath", "personaPath", "controlRuntimePath", "controlConfigPath", "controlRulesPath"):
        config[key] = expand_path(config[key])
    if not config.get("controlConfigPath"):
        config["controlConfigPath"] = config.get("controlRuntimePath", "")
    return config


def setup_logging(config):
    Path(config["logPath"]).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("wechat-ai-daemon")
    logger.setLevel(getattr(logging, str(config.get("logLevel", "INFO")).upper()))
    handler = RotatingFileHandler(config["logPath"], maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for old_handler in logger.handlers:
        old_handler.close()
    logger.handlers[:] = [handler]
    return logger


class RateLimiter:
    def __init__(self, min_interval_seconds, hourly_limit):
        self.min_interval_seconds = min_interval_seconds
        self.hourly_limit = hourly_limit
        self.last_reply = {}
        self.hourly = {}

    def allow(self, chat_id):
        now = time.time()
        if now - self.last_reply.get(chat_id, 0) < self.min_interval_seconds:
            return False
        window = [stamp for stamp in self.hourly.get(chat_id, []) if now - stamp < 3600]
        if len(window) >= self.hourly_limit:
            self.hourly[chat_id] = window
            return False
        window.append(now)
        self.hourly[chat_id] = window
        self.last_reply[chat_id] = now
        return True


class WeChatDaemon:
    def __init__(self, config, core=None, logger=None):
        self.config = config
        self.config.setdefault("controlConfigPath", self.config.get("controlRuntimePath", ""))
        self.core = core or wechat_core
        self.logger = logger or setup_logging(config)
        self.backoff = config["errorBackoffSeconds"]
        self.limiter = RateLimiter(config["perChatMinIntervalSeconds"], config["perChatHourlyLimit"])
        self.recent_replies = {}
        self.last_group_reply = {}
        self.instance_lock = config["activeWriterPath"] + ".daemon"
        self._effective_runtime = normalize_runtime({})
        self._loaded_reload_token = 0
        self._config_status = {
            "revision": 0,
            "source": "defaults",
            "loadedAt": None,
            "lastError": None,
            "interactionMode": self._effective_runtime["interactionMode"],
            "interactionEnforcement": self._effective_runtime["interactionEnforcement"],
            "idleTimeoutSeconds": self._effective_runtime["idleTimeoutSeconds"],
            "focusGraceSeconds": self._effective_runtime["focusGraceSeconds"],
            "automationLeaseSeconds": self._effective_runtime["automationLeaseSeconds"],
        }
        self._last_config_error = None
        self._last_config_log_marker = None
        self._interaction_guard = None
        self._interaction_guard_revision = None

    def _runtime_error(self):
        return {
            "code": "runtime_config_invalid",
            "message": "runtime configuration is invalid",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

    def _read_runtime_snapshot(self, path):
        path = Path(path)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("runtime configuration must be an object")
        return normalize_runtime(payload)

    def _log_config_reload(self, status):
        error = status.get("lastError") or {}
        marker = (status.get("revision"), status.get("source"), error.get("code"))
        if marker == self._last_config_log_marker:
            return
        self._last_config_log_marker = marker
        if error:
            self.logger.warning(
                "control config reload failed source=%s revision=%s code=%s",
                status.get("source"), status.get("revision"), error.get("code"),
            )
        else:
            self.logger.info(
                "control config loaded source=%s revision=%s",
                status.get("source"), status.get("revision"),
            )

    def reload_control_config(self):
        raw_config_path = self.config.get("controlConfigPath") or self.config.get("controlRuntimePath") or ""
        config_path = Path(raw_config_path) if raw_config_path else None
        last_good_path = config_path.with_name("runtime.last-good.json") if config_path else None
        value = None
        source = "defaults"
        error = None

        if last_good_path is not None:
            try:
                value = self._read_runtime_snapshot(config_path)
                if value is not None:
                    source = "runtime"
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                error = self._runtime_error()
            if value is None:
                try:
                    value = self._read_runtime_snapshot(last_good_path)
                    if value is not None:
                        source = "last-good"
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    value = None
        if value is None and self._effective_runtime:
            value = self._effective_runtime
            source = "last-good" if error else "defaults"
        if value is None:
            value = normalize_runtime({})

        self._effective_runtime = normalize_runtime(value)
        self._loaded_reload_token = self._effective_runtime["reloadToken"]
        self._last_config_error = error
        self._config_status = {
            "revision": self._loaded_reload_token,
            "source": source,
            "loadedAt": datetime.now(timezone.utc).isoformat(),
            "lastError": error,
            "interactionMode": self._effective_runtime["interactionMode"],
            "interactionEnforcement": self._effective_runtime["interactionEnforcement"],
            "idleTimeoutSeconds": self._effective_runtime["idleTimeoutSeconds"],
            "focusGraceSeconds": self._effective_runtime["focusGraceSeconds"],
            "automationLeaseSeconds": self._effective_runtime["automationLeaseSeconds"],
        }
        self._configure_interaction_guard()
        self._log_config_reload(self._config_status)
        return dict(self._effective_runtime)

    def _configure_interaction_guard(self):
        enforcement = self._effective_runtime.get("interactionEnforcement", "observe_only")
        if enforcement != "enforce" or InteractionArbiter is None or SendGuard is None or VmActivitySource is None or VmWindowAdapter is None:
            self._interaction_guard = None
            self._interaction_guard_revision = self._loaded_reload_token
            return
        if self._interaction_guard is not None and self._interaction_guard_revision == self._loaded_reload_token:
            return
        vm_window = VmWindowAdapter.from_environment()
        self._interaction_guard = SendGuard(InteractionArbiter(
            vm_window,
            activity_source=VmActivitySource(vm_window),
            idle_timeout_seconds=self._effective_runtime["idleTimeoutSeconds"],
            focus_grace_seconds=self._effective_runtime["focusGraceSeconds"],
            automation_lease_seconds=self._effective_runtime["automationLeaseSeconds"],
            pause_on_vm_file_transaction=self._effective_runtime["pauseOnVmFileTransaction"],
            pause_on_unknown_vm_state=self._effective_runtime["pauseOnUnknownVmState"],
        ))
        self._interaction_guard_revision = self._loaded_reload_token

    def config_status(self):
        self.reload_control_config()
        return dict(self._config_status)

    def _update_active_writer_metadata(self):
        path = Path(self.config.get("activeWriterPath", ""))
        if not path.is_file():
            return
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                return
            metadata.update({
                "controlConfigRevision": self._config_status["revision"],
                "controlConfigSource": self._config_status["source"],
                "controlConfigLoadedAt": self._config_status["loadedAt"],
                "controlConfigError": self._config_status["lastError"],
                "interactionMode": self._config_status["interactionMode"],
                "interactionEnforcement": self._config_status["interactionEnforcement"],
                "idleTimeoutSeconds": self._config_status["idleTimeoutSeconds"],
                "focusGraceSeconds": self._config_status["focusGraceSeconds"],
                "automationLeaseSeconds": self._config_status["automationLeaseSeconds"],
            })
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=path.name, dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(metadata, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        except (OSError, ValueError, TypeError):
            self.logger.warning("could not update active writer config metadata")

    def model_config(self):
        path = Path(self.config["siliconflowConfigPath"])
        merged = {
            "apiKey": os.environ.get("SILICONFLOW_API_KEY", ""),
            "baseUrl": os.environ.get("SILICONFLOW_BASE_URL", wechat_core.SILICONFLOW_DEFAULT_BASE_URL),
        }
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8-sig"))
            merged.update({key: value for key, value in stored.items() if value})
        merged.update(self.config)
        persona_path = Path(self.config["personaPath"])
        if persona_path.exists():
            persona = persona_path.read_text(encoding="utf-8").strip()
            if persona:
                merged["personaInstruction"] = persona
        if build_runtime_gateway is not None:
            rules_path = Path(self.config.get("controlRulesPath", ""))
            providers_path = rules_path.parent / "providers.json"
            if rules_path.exists() and providers_path.exists():
                try:
                    gateway = build_runtime_gateway(rules_path, providers_path)
                    if gateway is not None:
                        merged["modelGateway"] = gateway
                except Exception:
                    self.logger.exception("failed to build model gateway")
        return merged

    def _send_reply_result(self, chat, text):
        guard = self._interaction_guard
        if guard is None:
            if self._effective_runtime.get("interactionEnforcement") == "enforce":
                self.logger.error("send blocked chat=%s reason=interaction_guard_unavailable", chat.get("id"))
                return {"sent": False, "blocked": True, "reason": "interaction_guard_unavailable"}
            return self.core.send_reply_result(chat, text)
        ticket = guard.acquire(chat)
        if not getattr(ticket, "allowed", False):
            self.logger.warning("send blocked chat=%s reason=%s", chat.get("id"), ticket.reason)
            return {"sent": False, "blocked": True, "reason": ticket.reason}
        decision = guard.verify(ticket, chat)
        if not decision.allowed:
            self.logger.warning("send blocked chat=%s reason=%s", chat.get("id"), decision.reason)
            return {"sent": False, "blocked": True, "reason": decision.reason}
        guard.mark_automation_activity()
        try:
            result = self.core.send_reply_result(chat, text)
        except Exception:
            guard.finish(ticket, sent=False)
            raise
        guard.finish(ticket, sent=bool(result.get("sent")))
        return result

    def _logged_in_user_id(self):
        getter = getattr(self.core, "get_logged_in_user_id", None)
        if not callable(getter):
            return ""
        return str(getter() or "")

    def _list_messages(self, chat_id, limit, logged_in_user=""):
        messages = self.core.list_messages(chat_id, limit=limit)
        marker = getattr(self.core, "mark_self_messages", None)
        if logged_in_user and callable(marker):
            return marker(messages, logged_in_user)
        return messages

    @staticmethod
    def _fingerprint_message(message):
        if message.get("type") != 1:
            return ""
        return "".join(str(message.get("content") or "").split()).casefold()

    def _filter_duplicate_messages(self, chat_id, messages):
        now = time.time()
        recent = self.recent_replies.setdefault(chat_id, {})
        for fingerprint, stamp in list(recent.items()):
            if now - stamp > DUPLICATE_WINDOW_SECONDS:
                del recent[fingerprint]
        fresh = []
        for message in messages:
            fingerprint = self._fingerprint_message(message)
            if fingerprint and fingerprint in recent:
                self.logger.info("suppressed duplicate chat=%s localId=%s", chat_id, message.get("localId"))
                continue
            fresh.append(message)
        return fresh

    def _remember_replied_messages(self, chat_id, messages):
        recent = self.recent_replies.setdefault(chat_id, {})
        now = time.time()
        for message in messages:
            fingerprint = self._fingerprint_message(message)
            if fingerprint:
                recent[fingerprint] = now

    @staticmethod
    def _group_candidates(messages, recent_messages=None):
        candidates = []
        for message in messages:
            if not wechat_core.is_textual_message(message):
                continue
            text = wechat_core.message_text_for_safety(message)
            if wechat_core.is_no_reply_request(text):
                continue
            if wechat_core.is_malicious_request(text):
                continue
            if wechat_core.is_prompt_injection(text):
                continue
            if wechat_core.is_high_risk(text):
                continue
            candidate = dict(message)
            candidate["_replyToAi"] = wechat_core.is_direct_reply_to_ai(
                message,
                recent_messages or messages,
            )
            candidates.append(candidate)
        return candidates

    def _should_reply_to_group(self, group_id, messages):
        if not messages:
            return False
        patterns = [wechat_core.normalize_text(value) for value in (self.config.get("groupMentionPatterns") or [])]
        forced = any(
            bool(message.get("isMentioned"))
            or bool(message.get("_replyToAi"))
            or any(pattern and pattern in wechat_core.normalize_text(message.get("content") or "") for pattern in patterns)
            for message in messages
        )
        now = time.time()
        last_reply = self.last_group_reply.get(group_id, 0)
        active = now - last_reply < self.config["groupActiveWindowSeconds"]
        if forced:
            min_interval = self.config["groupActiveMentionMinIntervalSeconds"] if active else self.config["groupMentionMinIntervalSeconds"]
            return now - last_reply >= min_interval
        min_interval = self.config["groupActiveMinIntervalSeconds"] if active else self.config["groupMinIntervalSeconds"]
        probability = self.config["groupActiveReplyProbability"] if active else self.config["groupReplyProbability"]
        if now - last_reply < min_interval:
            return False
        return random.random() < probability

    def process_groups(self, state, chats, logged_in_user=""):
        allowed = {str(value) for value in (self.config.get("groupChatIds") or [])}
        if not allowed:
            return
        for chat in chats or []:
            group_id = str(chat.get("id") or "")
            if group_id not in allowed or not chat.get("isGroup"):
                continue
            current = self.core.last_seen(state, group_id)
            latest = chat.get("lastMsgLocalId")
            if not isinstance(latest, int) or latest <= current:
                continue
            messages = self._list_messages(group_id, limit=100, logged_in_user=logged_in_user)
            new_messages = [
                message for message in messages
                if (message.get("localId") or 0) > current and not message.get("isSelf")
            ]
            max_id = max([
                message.get("localId") or 0
                for message in messages
                if (message.get("localId") or 0) > current
            ] + [0])
            candidates = self._group_candidates(new_messages, messages)
            should_reply = bool(candidates) and self._should_reply_to_group(group_id, candidates)
            if not should_reply:
                if candidates:
                    self.logger.info("group skip chat=%s candidates=%d", group_id, len(candidates))
                if max_id:
                    wechat_core.set_last_seen(state, group_id, max_id)
                    self.core.save_state(self.config["statePath"], state)
                continue
            reply_chat = dict(chat)
            configured_name = (self.config.get("groupChatNames") or {}).get(group_id)
            if configured_name:
                reply_chat["name"] = str(configured_name)
            context = [
                message for message in (self._list_messages(group_id, limit=20, logged_in_user=logged_in_user) or candidates)
                if wechat_core.is_textual_message(message)
            ] or candidates
            group_config = self.model_config()
            group_config["replyInstruction"] = self.config.get("groupReplyInstruction") or ""
            try:
                result = self.core.generate_reply_result(reply_chat, context, group_config)
                text = result["reply"][: self.config["groupMaxReplyChars"]]
                sent = self._send_reply_result(reply_chat, text)
                self.logger.info("group send result chat=%s sent=%s", group_id, sent.get("sent"))
            except Exception:
                self.logger.exception("group reply failed chat=%s; leaving messages for retry", group_id)
                continue
            if sent.get("sent"):
                self.last_group_reply[group_id] = time.time()
                if max_id:
                    wechat_core.set_last_seen(state, group_id, max_id)
                self.core.save_state(self.config["statePath"], state)

    def write_heartbeat(self):
        path = Path(self.config["heartbeatPath"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        self._update_active_writer_metadata()

    def status(self):
        config_status = self.config_status()
        state = self.core.load_state(self.config["statePath"])
        writer = self.core.writer_status(self.config["activeWriterPath"])
        pending = state.get("pending", {})
        return {
            "mode": self.config.get("daemonMode"),
            "activeWriter": writer,
            "unlocked": len(state.get("unlocked", {})),
            "pendingChats": len(pending),
            "pendingMessages": sum(len(items) for items in pending.values()),
            "controlConfigRevision": config_status["revision"],
            "controlConfigSource": config_status["source"],
            "controlConfigError": config_status["lastError"],
            "interactionMode": config_status["interactionMode"],
            "idleTimeoutSeconds": config_status["idleTimeoutSeconds"],
        }


    def _resolved_rule(self, chat_id, is_group=False):
        path = Path(self.config.get("controlRulesPath", ""))
        if not path.exists():
            return {"instruction": "", "reply_mode": "auto"}
        payload = json.loads(path.read_text(encoding="utf-8"))
        active = []
        for rule in payload.get("rules", []):
            if not rule.get("enabled", True):
                continue
            scope = rule.get("scope")
            if scope == "global" or rule.get("target_id") == chat_id:
                if scope == "group" and not is_group:
                    continue
                active.append(rule)
        rank = {"temporary": 4, "contact": 3, "group": 2, "global": 1}
        active.sort(key=lambda item: (rank.get(item.get("scope"), 0), int(item.get("priority", 0))), reverse=True)
        resolved = {"instruction": "", "reply_mode": "auto"}
        for rule in reversed(active):
            resolved["instruction"] = rule.get("instruction") or resolved["instruction"]
            resolved["reply_mode"] = rule.get("reply_mode") or resolved["reply_mode"]
        return resolved

    def process_once(self):
        self.reload_control_config()
        if not self.core.acquire_writer(self.instance_lock):
            self.logger.warning("another daemon instance is already running")
            return {"activeWriter": False, "events": []}
        live = self.config.get("daemonMode") == "live"
        if live and not self.core.acquire_writer(self.config["activeWriterPath"]):
            self.logger.warning("writer lock is held; staying in shadow mode")
            if not live:
                self.core.release_writer(self.instance_lock)
            return {"activeWriter": False, "events": []}
        self._update_active_writer_metadata()
        if self._effective_runtime.get("paused"):
            self.logger.info("auto-reply paused")
            self.write_heartbeat()
            return {"activeWriter": True, "events": [], "paused": True}
        try:
            state = self.core.load_state(self.config["statePath"])
            logged_in_user = self._logged_in_user_id()
            chats = self.core.list_chats(limit=1000)
            messages_by_chat = {}
            test_chat_ids = set(self.config.get("testChatIds") or [])
            for chat in chats:
                if not self.core.chat_is_eligible(chat, test_chat_ids):
                    continue
                latest = chat.get("lastMsgLocalId")
                if isinstance(latest, int) and latest <= self.core.last_seen(state, chat["id"]):
                    continue
                messages_by_chat[chat["id"]] = self._list_messages(
                    chat["id"],
                    limit=100,
                    logged_in_user=logged_in_user,
                )
            events = self.core.build_poll_events(
                chats,
                messages_by_chat,
                state,
                self.config["unlockKeyword"],
                extra_eligible_ids=test_chat_ids,
            )
            if events:
                self.logger.info("events=%d", len(events))
            if not live:
                self.logger.info("shadow events=%d", len(events))
                self.write_heartbeat()
                self.core.release_writer(self.instance_lock)
                return {"activeWriter": True, "events": events}
            pending_by_chat = {}
            for event in events:
                if event.get("type") == "unlock":
                    chat = event["chat"]
                    self.logger.info("unlock confirmation chat=%s", chat.get("id"))
                    sent = self._send_reply_result(chat, event.get("confirmation") or "")
                    if sent.get("sent"):
                        self.core.save_state(self.config["statePath"], state)
                    continue
                if event.get("type") != "pending_message":
                    continue
                chat = event["chat"]
                group = pending_by_chat.setdefault(chat["id"], {"chat": chat, "messages": []})
                group["messages"].append(event["message"])

            for group in pending_by_chat.values():
                chat = group["chat"]
                effective = self._resolved_rule(chat["id"], bool(chat.get("isGroup")))
                if effective.get("reply_mode") == "silent":
                    self.core.acknowledge_pending(state, chat["id"])
                    self.core.save_state(self.config["statePath"], state)
                    continue
                if effective.get("reply_mode") == "manual":
                    continue
                messages = self._filter_duplicate_messages(chat["id"], group["messages"])
                if not messages:
                    self.core.acknowledge_pending(state, chat["id"])
                    self.core.save_state(self.config["statePath"], state)
                    continue
                self.logger.info("pending batch chat=%s count=%d", chat.get("id"), len(messages))
                safety_reply = ""
                has_vision_media = any(message.get("type") in (3, 47) for message in messages)
                for message in messages:
                    reply_for_message = getattr(self.core, "fixed_reply_for_message", None)
                    if callable(reply_for_message):
                        reply = reply_for_message(message)
                    else:
                        reply = self.core.fixed_reply_for(message.get("content") or "", message.get("type", 1))
                    if not reply:
                        continue
                    if has_vision_media and not wechat_core.is_textual_message(message):
                        continue
                    safety_reply = reply
                    break
                if safety_reply:
                    self.logger.info("safety reply chat=%s", chat.get("id"))
                    sent = self._send_reply_result(chat, safety_reply)
                    if sent.get("sent"):
                        self._remember_replied_messages(chat["id"], messages)
                        self.core.acknowledge_pending(state, chat["id"])
                        self.core.save_state(self.config["statePath"], state)
                    continue
                if not self.limiter.allow(chat["id"]):
                    self.logger.warning("rate limited chat=%s", chat["id"])
                    continue
                context = self._list_messages(chat["id"], limit=20, logged_in_user=logged_in_user) or messages
                recent_text = [item for item in context if wechat_core.is_textual_message(item)][-5:]
                pending_media = [item for item in messages if item.get("type") in (3, 47)]
                context = recent_text + pending_media or messages
                model_config = self.model_config()
                if effective.get("instruction"):
                    model_config["replyInstruction"] = ((model_config.get("replyInstruction") or "") + " " + effective["instruction"]).strip()
                result = self.core.generate_reply_result(chat, context, model_config)
                self.logger.info("generated chat=%s route=%s model=%s", chat.get("id"), result.get("route"), result.get("model"))
                text = result["reply"][: self.config["maxReplyChars"]]
                sent = self._send_reply_result(chat, text)
                self.logger.info("send result chat=%s sent=%s", chat.get("id"), sent.get("sent"))
                if sent.get("sent"):
                    self._remember_replied_messages(chat["id"], messages)
                    self.core.acknowledge_pending(state, chat["id"])
                    self.core.save_state(self.config["statePath"], state)
            self.process_groups(state, chats, logged_in_user=logged_in_user)
            self.core.save_state(self.config["statePath"], state)
            self.write_heartbeat()
            return {"activeWriter": True, "events": events}
        except Exception:
            self.logger.exception("daemon loop failed")
            time.sleep(self.backoff)
            self.backoff = min(self.backoff * 2, self.config["maxBackoffSeconds"])
            return {"activeWriter": live, "events": []}

    def run_forever(self):
        stop_flag = Path(self.config["stopFlagPath"])
        try:
            while not stop_flag.exists():
                self.process_once()
                self.backoff = self.config["errorBackoffSeconds"]
                time.sleep(self.config["pollIntervalSeconds"])
        finally:
            self.core.release_writer(self.instance_lock)
            if self.config.get("daemonMode") == "live":
                self.core.release_writer(self.config["activeWriterPath"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(state_dir() / "daemon.json"))
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    runner = WeChatDaemon(config)
    if args.status:
        print(json.dumps(runner.status(), ensure_ascii=False, indent=2))
        return
    runner.run_forever()


if __name__ == "__main__":
    main()
