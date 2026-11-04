import json

from .models import ProposedOperation


ALLOWED_OPS = {
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
}
HIGH_RISK_OPS = {"send_message", "lock_chat", "dismiss_pending", "retry_send", "rollback_change"}
TARGETED_OPS = {
    "set_contact_rule",
    "set_group_rule",
    "set_temporary_rule",
    "send_message",
    "lock_chat",
    "dismiss_pending",
    "retry_send",
}
FORBIDDEN_KEYS = {"cmd", "command", "path", "file", "url", "script", "credential", "api_key", "password"}


class CommandParser:
    def __init__(self, gateway, known_chat_ids, known_provider_ids, store=None):
        self.gateway = gateway
        self.known_chat_ids = set(known_chat_ids)
        self.known_provider_ids = set(known_provider_ids)
        self.store = store

    def parse(self, text, default_target_id=None):
        prompt = (
            "你是本机微信 AI 控制台的结构化指令解析器。"
            "只输出 JSON，不要解释。"
            "所有操作必须来自白名单。"
            "禁止输出 shell、文件路径、URL、凭据、任意代码操作。"
            "解锁操作不存在，任何 unlock_chat 都必须拒绝。"
            "返回格式：{\"operations\":[{\"op\":\"set_contact_rule\",\"payload\":{},\"risk\":\"low\",\"summary\":\"\"}]}。"
        )
        user_content = text
        if default_target_id:
            user_content = f"当前会话 ID：{default_target_id}\n用户要求：{text}"
        result = self.gateway.complete(
            "instruction_parser",
            [{"role": "system", "content": prompt}, {"role": "user", "content": user_content}],
            json_mode=True,
        )
        payload = json.loads(result.text)
        operations = [ProposedOperation(**item) for item in payload.get("operations", [])]
        if default_target_id:
            for operation in operations:
                if operation.op in TARGETED_OPS and not operation.payload.get("target_id"):
                    operation.payload["target_id"] = default_target_id
        self.validate(operations)
        return operations

    def validate(self, operations):
        for operation in operations:
            if operation.op not in ALLOWED_OPS:
                raise ValueError(f"forbidden op: {operation.op}")
            if operation.op == "unlock_chat":
                raise ValueError("unlock is unavailable in the console")
            if any(key in operation.payload for key in FORBIDDEN_KEYS):
                raise ValueError("forbidden payload key")
            if operation.op in TARGETED_OPS:
                target_id = operation.payload.get("target_id")
                if target_id not in self.known_chat_ids:
                    raise ValueError(f"unknown target: {target_id}")
            if operation.op == "set_model_route":
                provider_id = operation.payload.get("provider_id")
                if provider_id not in self.known_provider_ids:
                    raise ValueError(f"unknown provider: {provider_id}")
            expected_risk = "high" if operation.op in HIGH_RISK_OPS else "low"
            if operation.risk != expected_risk:
                raise ValueError(f"risk mismatch for {operation.op}")
        return operations

    def preview(self, operations):
        return {"operations": [item.model_dump() for item in operations], "highRisk": [item.op for item in operations if item.risk == "high"]}

    def apply(self, command_id, operations):
        if self.store is None:
            raise RuntimeError("store is required")
        self.store.update_command(command_id, "applied")
        self.store.audit("command.apply", command_id, "applied natural language command", {"operations": [item.model_dump() for item in operations]})
        return {"commandId": command_id, "status": "applied"}

    def rollback(self, command_id):
        if self.store is None:
            raise RuntimeError("store is required")
        self.store.update_command(command_id, "rolled_back")
        self.store.audit("command.rollback", command_id, "rolled back natural language command", {})
        return {"commandId": command_id, "status": "rolled_back"}
