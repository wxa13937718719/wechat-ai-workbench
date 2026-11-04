from datetime import datetime, timezone

import httpx

from .models import ProviderConfig


class KeyringCredentialStore:
    def __init__(self, service_name="wechat-ai-reply-console"):
        try:
            import keyring
        except Exception:
            keyring = None
        self.keyring = keyring
        self.service_name = service_name

    def set(self, provider_id, api_key):
        if self.keyring is None:
            return False
        try:
            self.keyring.set_password(self.service_name, provider_id, api_key)
        except Exception:
            return False
        return True

    def get(self, provider_id):
        if self.keyring is None:
            return None
        try:
            return self.keyring.get_password(self.service_name, provider_id)
        except Exception:
            return None

    def delete(self, provider_id):
        if self.keyring is None:
            return False
        try:
            self.keyring.delete_password(self.service_name, provider_id)
        except Exception:
            return False
        return True


class ProviderRegistry:
    def __init__(self, store, credential_store, http_client=None):
        self.store = store
        self.credential_store = credential_store
        self.http = http_client or httpx.Client(timeout=15)

    def list_providers(self):
        return [ProviderConfig(**item) for item in self.store.read_providers().get("providers", [])]

    def _write(self, providers):
        self.store.write_providers({"providers": [item.model_dump() for item in providers]})

    def upsert_provider(self, payload, api_key=None):
        providers = {item.id: item for item in self.list_providers()}
        provider = ProviderConfig(**payload)
        providers[provider.id] = provider
        self._write(list(providers.values()))
        if api_key:
            self.credential_store.set(provider.id, api_key)
        return provider.model_dump()

    def delete_provider(self, provider_id):
        providers = [item for item in self.list_providers() if item.id != provider_id]
        self._write(providers)
        self.credential_store.delete(provider_id)

    def _get(self, provider_id):
        for provider in self.list_providers():
            if provider.id == provider_id:
                return provider
        raise KeyError(provider_id)

    def _headers(self, provider):
        key = self.credential_store.get(provider.id)
        return {"Authorization": f"Bearer {key}"} if key else {}

    def discover_models(self, provider_id):
        provider = self._get(provider_id)
        if provider.kind in {"openai_compatible", "siliconflow"}:
            response = self.http.get(provider.base_url.rstrip("/") + "/v1/models", headers=self._headers(provider))
            response.raise_for_status()
            models = [item["id"] for item in response.json().get("data", [])]
        elif provider.kind == "ollama":
            response = self.http.get(provider.base_url.rstrip("/") + "/api/tags")
            response.raise_for_status()
            models = [item["name"] for item in response.json().get("models", [])]
        else:
            raise ValueError(f"unsupported provider kind: {provider.kind}")
        provider.models = models
        provider.last_discovered_at = datetime.now(timezone.utc).isoformat()
        providers = {item.id: item for item in self.list_providers()}
        providers[provider.id] = provider
        self._write(list(providers.values()))
        return models

    def test_provider(self, provider_id):
        try:
            models = self.discover_models(provider_id)
            return {"ok": True, "models": models}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
