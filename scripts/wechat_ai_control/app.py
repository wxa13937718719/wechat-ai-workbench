import types
import urllib.parse
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .actions import ActionCenter
from .api_errors import ApiError, error_response
from .command_parser import CommandParser
from .config_store import ConfigStore
from .interaction import InteractionArbiter
from .mirror import WeChatMirror
from .model_gateway import ModelGateway
from .models import AppConfig
from .providers import KeyringCredentialStore, ProviderRegistry
from .rules_api import create_rules_router
from .runtime import RuntimeBridge
from .transfer import TransferCoordinator
from .updates import UpdateFeed
from .vm_activity import VmActivitySource
from .vm_window import VmWindowAdapter
from .wechat_mirror.media import MediaNotDownloaded, MediaNotFound
from .wechat_mirror.sqlcipher import DatabaseUnavailable, SchemaMismatch


def create_app(config: AppConfig, *, store=None, provider_registry=None, gateway=None, known_chat_ids=None, runtime=None, update_feed=None) -> FastAPI:
    package_dir = Path(__file__).resolve().parent
    app = FastAPI(title="微信 AI 控制台")
    app.state.config = config
    store = store or ConfigStore(config.state_dir)
    actions = ActionCenter(store)
    if provider_registry is None:
        provider_registry = ProviderRegistry(store, KeyringCredentialStore())
    store.ensure_legacy_provider(
        config.state_dir / "siliconflow.json",
        getattr(provider_registry, "credential_store", None),
    )
    gateway_injected = gateway is not None
    routes = store.read_rules().get("routes", {})
    if gateway is None:
        gateway = ModelGateway(provider_registry, routes, credential_lookup=provider_registry.credential_store.get)
    if runtime is None:
        import wechat_ai_reply as wechat_core
        adapter = types.SimpleNamespace(
            resolve_chat=wechat_core.resolve_chat,
            send_message=wechat_core.send_message,
            is_unlocked=wechat_core.is_unlocked,
            ai_control_status=wechat_core.ai_control_status,
            grant_ai_access=wechat_core.grant_ai_access,
            revoke_ai_access=wechat_core.revoke_ai_access,
            acknowledge_pending=wechat_core.acknowledge_pending,
            save_state=wechat_core.save_state,
            list_chats=wechat_core.list_chats,
            list_contacts=wechat_core.list_contacts,
            list_messages=wechat_core.list_messages,
            get_message_media=lambda chat_id, local_id: wechat_core.api(
                "GET",
                f"/api/messages/{urllib.parse.quote(chat_id, safe='')}/media/{int(local_id)}",
            ),
            open_chat=lambda chat_id: wechat_core.api(
                "POST",
                f"/api/chats/{urllib.parse.quote(chat_id, safe='')}/open?clearUnreads=false",
            ),
        )
        vm_window = VmWindowAdapter.from_environment()
        interaction = InteractionArbiter(
            vm_window,
            activity_source=VmActivitySource(vm_window),
            idle_timeout_seconds=store.read_runtime().get("idleTimeoutSeconds", 60),
            focus_grace_seconds=store.read_runtime().get("focusGraceSeconds", 5),
            automation_lease_seconds=store.read_runtime().get("automationLeaseSeconds", 20),
            pause_on_vm_file_transaction=store.read_runtime().get("pauseOnVmFileTransaction", True),
            pause_on_unknown_vm_state=store.read_runtime().get("pauseOnUnknownVmState", True),
        )
        runtime = RuntimeBridge(
            store,
            adapter,
            config.state_dir / "state.json",
            config.state_dir / "daemon.active",
            mirror=WeChatMirror(message_source=adapter, media_open_chat=adapter.open_chat),
            interaction=interaction,
            transfer=TransferCoordinator(interaction),
        )
    known_chat_ids = set(known_chat_ids or [])
    if update_feed is None:
        if hasattr(runtime, "snapshot"):
            snapshot_provider = runtime.snapshot
        else:
            snapshot_provider = lambda: {"chats": runtime.list_chats(), "daemonRevision": {}}
        update_feed = UpdateFeed(snapshot_provider)
    parser = None
    if gateway_injected or "instruction_parser" in routes:
        parser = CommandParser(gateway, known_chat_ids, {provider.id for provider in provider_registry.list_providers()}, store)

    def refresh_parser_targets(chat_ids=()):
        if parser is None:
            return
        parser.known_provider_ids = {provider.id for provider in provider_registry.list_providers()}
        for chat_id in chat_ids:
            if not chat_id:
                continue
            runtime.get_chat(chat_id)
            parser.known_chat_ids.add(chat_id)
    app.include_router(create_rules_router(store, parser=parser))
    app.mount("/static", StaticFiles(directory=package_dir / "web" / "static"), name="static")
    templates = Jinja2Templates(directory=package_dir / "web" / "templates")

    @app.middleware("http")
    async def local_token_middleware(request: Request, call_next):
        if config.local_token and request.url.path.startswith("/api/"):
            if request.headers.get("X-Local-Token") != config.local_token:
                return error_response(ApiError("unauthorized", "未授权", status_code=401))
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError):
        return error_response(exc)

    @app.exception_handler(DatabaseUnavailable)
    async def handle_database_unavailable(_request: Request, _exc: DatabaseUnavailable):
        return error_response(ApiError(
            "wechat_database_unavailable",
            "微信数据库暂时不可用",
            status_code=503,
            retryable=True,
        ))

    @app.exception_handler(SchemaMismatch)
    async def handle_schema_mismatch(_request: Request, _exc: SchemaMismatch):
        return error_response(ApiError(
            "wechat_schema_mismatch",
            "微信数据库结构暂不兼容",
            status_code=409,
            retryable=False,
        ))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError):
        fields = [
            {
                "location": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg") or "invalid value"),
            }
            for error in exc.errors()
        ]
        return error_response(ApiError(
            "invalid_request",
            "请求参数无效",
            status_code=422,
            details={"fields": fields},
        ))

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "mode": "local"}

    @app.get("/api/status")
    async def status():
        payload = runtime.status()
        if "transfer" not in payload:
            payload = dict(payload)
            payload["transfer"] = runtime_transfer_status()
        return payload

    def runtime_transfer_status():
        if hasattr(runtime, "transfer_status"):
            return runtime.transfer_status()
        current = runtime.status()
        if isinstance(current, dict) and isinstance(current.get("transfer"), dict):
            return current["transfer"]
        return {
            "transactionId": None,
            "source": "unknown",
            "stage": "idle",
            "active": False,
            "itemCount": 0,
            "startedAt": None,
            "finishedAt": None,
            "outcome": None,
            "errorCode": "transfer_status_unavailable",
            "enforcement": "observe_only",
        }

    @app.get("/api/transfers/status")
    async def transfer_status():
        return runtime_transfer_status()

    @app.get("/api/interaction")
    async def interaction_status():
        if hasattr(runtime, "interaction_status"):
            return runtime.interaction_status()
        return runtime.status().get("interaction", {
            "state": "PAUSED_UNKNOWN",
            "reason": "interaction_status_unavailable",
            "canAutomate": False,
            "enforcement": "observe_only",
        })

    def runtime_configuration_status(runtime_status=None):
        if hasattr(runtime, "config_status"):
            return runtime.config_status()
        saved_status = store.runtime_status()
        saved = {
            "reloadToken": saved_status["savedReloadToken"],
            "source": saved_status["source"],
            "lastError": saved_status["lastError"],
        }
        current = runtime_status if isinstance(runtime_status, dict) else runtime.status()
        active = current.get("activeWriter") if isinstance(current.get("activeWriter"), dict) else {}
        effective = {
            "reloadToken": current.get("controlConfigRevision", active.get("controlConfigRevision")),
            "source": current.get("controlConfigSource", active.get("controlConfigSource", "unknown")),
            "loadedAt": current.get("controlConfigLoadedAt", active.get("controlConfigLoadedAt")),
            "lastError": current.get("controlConfigError", active.get("controlConfigError")),
            "interactionMode": current.get("interactionMode", active.get("interactionMode")),
            "idleTimeoutSeconds": current.get("idleTimeoutSeconds", active.get("idleTimeoutSeconds")),
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

    @app.get("/api/config/status")
    async def config_status():
        return runtime_configuration_status()

    @app.get("/api/capabilities")
    async def capabilities():
        if hasattr(runtime, "capabilities"):
            return runtime.capabilities()
        return {name: False for name in ("sendText", "sendImage", "sendFile", "sendSticker", "playVoice", "openMedia")}

    @app.get("/api/updates")
    def updates(since: int = 0):
        return update_feed.poll(since)

    @app.get("/api/chats")
    async def list_chats(cursor: str | None = None, limit: int = 100, query: str | None = None):
        if hasattr(runtime, "list_chat_page"):
            return runtime.list_chat_page(cursor=cursor, limit=limit, query=query)
        return {"chats": runtime.list_chats(), "nextCursor": None}

    @app.get("/api/chats/{chat_id}")
    async def get_chat(chat_id: str):
        return runtime.get_chat(chat_id)

    @app.get("/api/chats/{chat_id}/ai-control")
    async def get_chat_ai_control(chat_id: str):
        chat = runtime.get_chat(chat_id)
        is_group = chat.get("kind") == "group" or bool(chat.get("isGroup"))
        authorization = runtime.ai_control_status(chat_id) if hasattr(runtime, "ai_control_status") else {
            "unlocked": bool(chat.get("unlocked", False)),
            "source": None,
            "manualOverride": None,
            "keywordUnlockAllowed": True,
        }
        resolved = store.resolve_rule(chat_id, is_group=is_group)
        current_rules = store.read_rules()
        open_actions = [
            {
                "id": action.get("id"),
                "kind": action.get("kind"),
                "summary": action.get("summary"),
                "status": action.get("status"),
            }
            for action in actions.list()
            if action.get("target") == chat_id and action.get("status") in {"open", "retrying", "awaiting_confirmation"}
        ]
        last_ai_send = next((
            {
                "id": event.get("id"),
                "summary": event.get("summary"),
                "createdAt": event.get("created_at"),
            }
            for event in store.read_audit(limit=200)
            if event.get("target") == chat_id and event.get("kind") in {"ai.send", "reply.send"}
        ), None)
        status = runtime.status()
        health = "action-required" if open_actions else ("warning" if status.get("paused") or not status.get("activeWriter") else "healthy")
        return {
            "chatId": chat_id,
            "chatName": chat.get("name") or chat_id,
            "isGroup": is_group,
            "unlocked": bool(authorization.get("unlocked", False)),
            "authorizationSource": authorization.get("source"),
            "manualOverride": authorization.get("manualOverride"),
            "keywordUnlockAllowed": authorization.get("keywordUnlockAllowed", True),
            "replyMode": resolved.get("reply_mode", "auto"),
            "resolvedRule": resolved,
            "lastAiSend": last_ai_send,
            "nextAllowedGroupReplyAt": None,
            "modelRoute": (
                current_rules.get("routes", {}).get("text_reply", {}).get("primary")
                if isinstance(current_rules.get("routes", {}).get("text_reply"), dict)
                and "primary" in current_rules.get("routes", {}).get("text_reply", {})
                else current_rules.get("routes", {}).get("text_reply")
            ),
            "openActions": open_actions,
            "health": health,
        }

    @app.get("/api/chats/{chat_id}/messages")
    async def list_messages(chat_id: str, before: str | None = None, limit: int = 100):
        if hasattr(runtime, "list_message_page"):
            return runtime.list_message_page(chat_id, before=before, limit=limit)
        return {"messages": runtime.list_messages(chat_id, limit=limit), "nextCursor": None}

    @app.get("/api/chats/{chat_id}/messages/{local_id}/media")
    async def open_media(chat_id: str, local_id: int, request: Request):
        try:
            stream = runtime.open_media(chat_id, local_id)
        except MediaNotFound:
            raise ApiError("media_not_found", "媒体不存在", status_code=404) from None
        except MediaNotDownloaded:
            raise ApiError("media_not_downloaded", "媒体尚未下载", status_code=409, retryable=True) from None
        if request.headers.get("If-None-Match") == stream.etag:
            return Response(status_code=304, headers={"ETag": stream.etag, "Cache-Control": stream.cache_control})
        return Response(
            content=stream.data,
            media_type=stream.mime_type,
            headers={"ETag": stream.etag, "Cache-Control": stream.cache_control},
        )

    @app.post("/api/chats/{chat_id}/send")
    async def send_message(chat_id: str, request: Request):
        body = await request.json()
        return runtime.manual_send(
            chat_id,
            body.get("text", ""),
            client_request_id=body.get("clientRequestId"),
            retry_token=body.get("retryToken"),
        )

    @app.post("/api/chats/{chat_id}/mark-handled")
    async def mark_handled(chat_id: str):
        return runtime.mark_handled(chat_id)

    @app.post("/api/chats/{chat_id}/lock")
    async def lock_chat(chat_id: str):
        return runtime.lock_chat(chat_id)

    @app.post("/api/chats/{chat_id}/ai-control")
    async def set_chat_ai_control(chat_id: str, request: Request):
        body = await request.json()
        action = str(body.get("action") or "").strip().lower()
        if action not in {"grant", "revoke"}:
            raise ApiError("invalid_ai_control_action", "action 必须是 grant 或 revoke", status_code=422)
        return runtime.set_ai_control(chat_id, action)

    def operation_diff(operation, chat_id):
        payload = dict(operation.payload)
        target_id = payload.get("target_id") or chat_id
        before = None
        if operation.op in {"set_global_persona", "set_contact_rule", "set_group_rule", "set_temporary_rule"}:
            before = store.resolve_rule(target_id, is_group=operation.op == "set_group_rule")
        elif operation.op == "set_model_route":
            before = store.read_rules().get("routes", {}).get(payload.get("role") or "text_reply")
        elif operation.op == "set_runtime_setting":
            before = store.read_runtime()
        return {
            "op": operation.op,
            "target": target_id,
            "before": before,
            "after": payload,
            "risk": operation.risk,
            "summary": operation.summary,
        }

    @app.post("/api/commands/preview")
    async def preview_command(request: Request):
        if parser is None:
            raise ApiError("parser_unavailable", "指令解析模型未配置", status_code=503, retryable=True)
        body = await request.json()
        text = str(body.get("text") or "").strip()
        chat_id = str(body.get("chatId") or "")
        refresh_parser_targets([chat_id])
        operations = parser.parse(text, default_target_id=chat_id or None)
        command_id = uuid.uuid4().hex
        draft = {
            "id": command_id,
            "input_text": text,
            "operations": [item.model_dump() for item in operations],
            "status": "draft",
        }
        store.create_command(draft)
        diffs = [operation_diff(operation, chat_id) for operation in operations]
        return {
            "commandId": command_id,
            "status": "draft",
            "operations": diffs,
            "requiresConfirmation": any(item.risk == "high" for item in operations),
        }

    def apply_command_operations(command):
        from .models import ProposedOperation

        operations = [ProposedOperation(**item) for item in command.get("operations", [])]
        refresh_parser_targets([
            operation.payload.get("target_id")
            for operation in operations
            if operation.payload.get("target_id")
        ])
        parser.validate(operations)
        current = store.read_rules()
        rules = list(current.get("rules", []))
        routes = dict(current.get("routes", {}))
        rules_changed = False
        results = []
        for operation in operations:
            payload = dict(operation.payload)
            if operation.op in {"set_global_persona", "set_contact_rule", "set_group_rule", "set_temporary_rule"}:
                scope_map = {
                    "set_global_persona": "global",
                    "set_contact_rule": "contact",
                    "set_group_rule": "group",
                    "set_temporary_rule": "temporary",
                }
                scope = scope_map[operation.op]
                target_id = payload.get("target_id")
                rule_id = f"command-{scope}-{target_id or 'all'}"
                replacement = {
                    "id": rule_id,
                    "scope": scope,
                    "target_id": target_id,
                    "enabled": True,
                    "instruction": payload.get("instruction", ""),
                    "reply_mode": payload.get("reply_mode", "auto"),
                    "created_by": "model",
                }
                rules = [rule for rule in rules if rule.get("id") != rule_id]
                rules.append(replacement)
                rules_changed = True
                results.append({"op": operation.op, "status": "applied"})
            elif operation.op == "set_model_route":
                role = payload.get("role") or "text_reply"
                routes[role] = {key: payload.get(key) for key in ("provider_id", "model")}
                rules_changed = True
                results.append({"op": operation.op, "status": "applied"})
            elif operation.op == "set_runtime_setting":
                if "paused" in payload:
                    store.set_paused(bool(payload["paused"]), str(payload.get("reason") or ""))
                results.append({"op": operation.op, "status": "applied"})
            elif operation.op == "send_message":
                target = payload.get("target_id")
                results.append({"op": operation.op, "result": runtime.manual_send(target, str(payload.get("text") or ""))})
            elif operation.op == "dismiss_pending":
                results.append({"op": operation.op, "result": runtime.mark_handled(payload.get("target_id"))})
            elif operation.op == "lock_chat":
                results.append({"op": operation.op, "result": runtime.lock_chat(payload.get("target_id"))})
            elif operation.op == "retry_send":
                results.append({"op": operation.op, "result": runtime.manual_send(
                    payload.get("target_id"),
                    str(payload.get("text") or ""),
                    client_request_id=payload.get("client_request_id"),
                    retry_token=payload.get("retry_token"),
                )})
            elif operation.op == "rollback_change":
                results.append({"op": operation.op, "result": store.rollback_rules(int(payload.get("revision", 0)))})
            else:
                results.append({"op": operation.op, "status": "accepted"})
        if rules_changed:
            saved = store.write_rules({"rules": rules, "routes": routes}, expected_revision=current.get("revision"))
            gateway.routes = saved.get("routes", {})
        return operations, results

    @app.post("/api/commands/{command_id}/apply")
    async def apply_command(command_id: str, request: Request):
        command = store.read_command(command_id)
        if not command:
            raise ApiError("command_not_found", "指令草稿不存在", status_code=404)
        body = await request.json()
        high_risk = any(item.get("risk") == "high" for item in command.get("operations", []))
        if high_risk and not body.get("confirmHighRisk"):
            raise ApiError("confirmation_required", "高风险操作需要明确确认", status_code=409)
        operations, results = apply_command_operations(command)
        store.update_command(command_id, "applied")
        store.audit("command.apply", command_id, "applied natural language command", {
            "operations": [item.model_dump() for item in operations],
        })
        return {"commandId": command_id, "status": "applied", "results": results}

    @app.get("/api/audit")
    async def audit():
        return {"events": store.read_audit()}

    @app.get("/api/actions")
    async def list_actions():
        return {"actions": actions.list()}

    @app.post("/api/actions/{action_id}/retry")
    async def retry_action(action_id: str):
        return actions.retry(action_id)

    @app.post("/api/actions/{action_id}/dismiss")
    async def dismiss_action(action_id: str, request: Request):
        body = await request.json()
        return actions.dismiss(action_id, body.get("reason", ""))

    @app.post("/api/actions/{action_id}/confirm")
    async def confirm_action(action_id: str):
        return actions.confirm(action_id)

    @app.get("/api/routes")
    async def get_routes():
        return store.read_rules().get("routes", {})

    @app.post("/api/routes")
    async def set_routes(request: Request):
        body = await request.json()
        current = store.read_rules()
        saved = store.write_rules({"rules": current.get("rules", []), "routes": body.get("routes", {})}, expected_revision=current.get("revision"))
        gateway.routes = saved.get("routes", {})
        store.audit("route.apply", "routes", "updated model routes", {"revision": saved["revision"]})
        return saved

    @app.get("/api/runtime")
    async def get_runtime():
        runtime_status = runtime.status()
        if "transfer" not in runtime_status:
            runtime_status = dict(runtime_status)
            runtime_status["transfer"] = runtime_transfer_status()
        config_status = runtime_configuration_status(runtime_status)
        return {
            "settings": store.read_runtime(),
            "status": runtime_status,
            **config_status,
        }

    @app.post("/api/runtime")
    async def set_runtime(request: Request):
        body = await request.json()
        paused = bool(body.get("paused", False))
        if paused:
            settings = runtime.pause(str(body.get("reason") or "由控制台暂停"))
        else:
            settings = runtime.resume()
        reload_token = runtime.bump_reload()
        store.audit("runtime.apply", "runtime", "updated runtime state", {"paused": paused, "reloadToken": reload_token})
        return {"settings": settings, "reloadToken": reload_token}

    @app.post("/api/sandbox/run")
    async def run_sandbox(request: Request):
        body = await request.json()
        bridge = RuntimeBridge(store=store, wechat=None, state_path=config.state_dir / "state.json")
        return bridge.run_sandbox(body["chat_id"], body.get("text", ""), gateway, is_group=bool(body.get("is_group", False)))

    @app.get("/api/providers")
    async def list_providers():
        return {"providers": [provider.model_dump() if hasattr(provider, "model_dump") else {name: getattr(provider, name, None) for name in ("id", "kind", "name", "base_url", "credential_ref", "models", "last_discovered_at", "enabled")} for provider in provider_registry.list_providers()]}

    @app.post("/api/providers")
    async def upsert_provider(request: Request):
        body = await request.json()
        api_key = body.pop("api_key", None)
        return provider_registry.upsert_provider(body, api_key=api_key)

    @app.post("/api/providers/{provider_id}/discover")
    async def discover_provider(provider_id: str):
        return {"models": provider_registry.discover_models(provider_id)}

    @app.post("/api/providers/{provider_id}/test")
    async def test_provider(provider_id: str):
        return provider_registry.test_provider(provider_id)

    @app.get("/conversations", response_class=HTMLResponse)
    async def conversations(request: Request):
        return templates.TemplateResponse(request=request, name="conversations.html", context={})

    @app.get("/rules", response_class=HTMLResponse)
    async def rules_page(request: Request):
        return templates.TemplateResponse(request=request, name="rules.html", context={})

    @app.get("/models", response_class=HTMLResponse)
    async def models_page(request: Request):
        return templates.TemplateResponse(request=request, name="models.html", context={})

    @app.get("/commands", response_class=HTMLResponse)
    async def commands_page(request: Request):
        return templates.TemplateResponse(request=request, name="commands.html", context={})

    @app.get("/audit", response_class=HTMLResponse)
    async def audit_page(request: Request):
        return templates.TemplateResponse(request=request, name="audit.html", context={})

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(request=request, name="settings.html", context={})

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request=request, name="base.html", context={})

    return app
