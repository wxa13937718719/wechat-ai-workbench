from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


Scope = Literal["global", "contact", "group", "temporary"]
ReplyMode = Literal["auto", "manual", "silent"]
Risk = Literal["low", "high"]
Role = Literal[
    "text_reply",
    "vision_reply",
    "instruction_parser",
    "safety_classifier",
    "summarizer",
]


class RuntimeSettings(BaseModel):
    interactionMode: Literal["vm_human_aware", "observe", "draft"] = "vm_human_aware"
    interactionEnforcement: Literal["observe_only", "enforce"] = "observe_only"
    idleTimeoutSeconds: int = 60
    focusGraceSeconds: int = 5
    automationLeaseSeconds: int = 20
    pauseOnVmFileTransaction: bool = True
    pauseOnUnknownVmState: bool = True
    hostUnrelatedFileOpsAffectAi: bool = False
    sharedTransferDirectory: str = ""


RUNTIME_DEFAULTS = {
    "paused": False,
    "reason": "",
    "reloadToken": 0,
    "interactionMode": "vm_human_aware",
    "interactionEnforcement": "observe_only",
    "idleTimeoutSeconds": 60,
    "focusGraceSeconds": 5,
    "automationLeaseSeconds": 20,
    "pauseOnVmFileTransaction": True,
    "pauseOnUnknownVmState": True,
    "hostUnrelatedFileOpsAffectAi": False,
    "sharedTransferDirectory": "",
}


def _bounded_int(value, default, lower, upper):
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lower, min(upper, number))


def _strict_bool(value, default):
    return value if isinstance(value, bool) else default


def normalize_runtime(payload):
    raw = payload if isinstance(payload, dict) else {}
    mode = raw.get("interactionMode")
    normalized = {
        "paused": _strict_bool(raw.get("paused"), RUNTIME_DEFAULTS["paused"]),
        "reason": str(raw.get("reason") or ""),
        "reloadToken": _bounded_int(raw.get("reloadToken"), 0, 0, 2**63 - 1),
        "interactionMode": mode if mode in {"vm_human_aware", "observe", "draft"} else RUNTIME_DEFAULTS["interactionMode"],
        "interactionEnforcement": raw.get("interactionEnforcement") if raw.get("interactionEnforcement") in {"observe_only", "enforce"} else RUNTIME_DEFAULTS["interactionEnforcement"],
        "idleTimeoutSeconds": _bounded_int(raw.get("idleTimeoutSeconds"), 60, 15, 3600),
        "focusGraceSeconds": _bounded_int(raw.get("focusGraceSeconds"), 5, 0, 30),
        "automationLeaseSeconds": _bounded_int(raw.get("automationLeaseSeconds"), 20, 5, 120),
        "pauseOnVmFileTransaction": _strict_bool(raw.get("pauseOnVmFileTransaction"), True),
        "pauseOnUnknownVmState": _strict_bool(raw.get("pauseOnUnknownVmState"), True),
        "hostUnrelatedFileOpsAffectAi": _strict_bool(raw.get("hostUnrelatedFileOpsAffectAi"), False),
        "sharedTransferDirectory": str(raw.get("sharedTransferDirectory") or ""),
    }
    RuntimeSettings(**{key: normalized[key] for key in RUNTIME_DEFAULTS if key in RuntimeSettings.model_fields})
    return normalized


class AppConfig(BaseModel):
    state_dir: Path
    local_token: str | None = None
    host: str = "127.0.0.1"
    port: int = 8765


class Rule(BaseModel):
    id: str
    scope: Scope
    target_id: str | None = None
    enabled: bool = True
    priority: int = 0
    instruction: str = ""
    reply_mode: ReplyMode = "auto"
    frequency: dict[str, float] = Field(default_factory=dict)
    group_policy: dict[str, float] = Field(default_factory=dict)
    media_policy: dict[str, int] = Field(default_factory=dict)
    safety_mode: Literal["normal", "strict"] = "normal"
    expires_at: str | None = None
    created_by: Literal["user", "model"] = "user"
    version: int = 1


class ModelRef(BaseModel):
    provider_id: str
    model: str


class ModelRoute(BaseModel):
    role: Role
    primary: ModelRef
    fallbacks: list[ModelRef] = Field(default_factory=list)


class ProviderConfig(BaseModel):
    id: str
    kind: Literal["openai_compatible", "ollama", "siliconflow"]
    name: str
    base_url: str
    credential_ref: str | None = None
    credential_status: Literal["stored", "missing", "unavailable"] = "missing"
    models: list[str] = Field(default_factory=list)
    last_discovered_at: str | None = None
    enabled: bool = True


class ProposedOperation(BaseModel):
    op: Literal[
        "set_global_persona",
        "set_contact_rule",
        "set_group_rule",
        "set_temporary_rule",
        "set_model_route",
        "set_runtime_setting",
        "send_message",
        "lock_chat",
        "dismiss_pending",
        "retry_send",
        "rollback_change",
    ]
    payload: dict
    risk: Risk
    summary: str


class AuditEvent(BaseModel):
    id: str
    kind: str
    target: str
    summary: str
    payload: dict
    created_at: str
