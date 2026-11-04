import json
from pathlib import Path

try:
    from .model_gateway import ModelGateway
except ImportError:
    from model_gateway import ModelGateway


class JsonProvider:
    def __init__(self, payload):
        self.id = payload["id"]
        self.kind = payload.get("kind", "openai_compatible")
        self.name = payload.get("name", self.id)
        self.base_url = payload["base_url"]
        self.models = payload.get("models", [])
        self.enabled = payload.get("enabled", True)
        self.credential_ref = payload.get("credential_ref")


class JsonProviderRegistry:
    def __init__(self, providers):
        self.providers = [JsonProvider(item) for item in providers]

    def _get(self, provider_id):
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise KeyError(provider_id)


def _credential_lookup(provider_id):
    try:
        import keyring
        return keyring.get_password("wechat-ai-reply-console", provider_id)
    except Exception:
        return None


def build_runtime_gateway(rules_path, providers_path):
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    providers = json.loads(Path(providers_path).read_text(encoding="utf-8")).get("providers", [])
    routes = rules.get("routes", {})
    if not routes:
        return None
    return ModelGateway(JsonProviderRegistry(providers), routes, credential_lookup=_credential_lookup)
