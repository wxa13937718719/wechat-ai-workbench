from dataclasses import dataclass

import httpx


@dataclass
class ModelResult:
    provider_id: str
    model: str
    text: str
    usage: dict


class ModelGateway:
    def __init__(self, registry, routes, http_client=None, credential_lookup=None):
        self.registry = registry
        self.routes = routes
        self.http = http_client or httpx.Client(timeout=60)
        self.credential_lookup = credential_lookup or (lambda provider_id: None)

    def _provider(self, provider_id):
        return self.registry._get(provider_id)

    def _call_openai(self, provider, model, messages, json_mode):
        key = self.credential_lookup(provider.id)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        body = {"model": model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        response = self.http.post(provider.base_url.rstrip("/") + "/v1/chat/completions", headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        return ModelResult(provider.id, model, payload["choices"][0]["message"]["content"], payload.get("usage", {}))

    def _call_ollama(self, provider, model, messages, json_mode):
        body = {"model": model, "messages": messages, "stream": False}
        if json_mode:
            body["format"] = "json"
        response = self.http.post(provider.base_url.rstrip("/") + "/api/chat", json=body)
        response.raise_for_status()
        payload = response.json()
        return ModelResult(provider.id, model, payload["message"]["content"], payload.get("usage", {}))

    def _call(self, provider_id, model, messages, json_mode):
        provider = self._provider(provider_id)
        if provider.kind in {"openai_compatible", "siliconflow"}:
            return self._call_openai(provider, model, messages, json_mode)
        if provider.kind == "ollama":
            return self._call_ollama(provider, model, messages, json_mode)
        raise ValueError(f"unsupported provider kind: {provider.kind}")

    def complete(self, role, messages, json_mode=False):
        route = self.routes.get(role)
        if not route:
            raise KeyError(f"no model route for role: {role}")
        candidates = [route["primary"]] + list(route.get("fallbacks", []))
        errors = []
        for candidate in candidates:
            try:
                return self._call(candidate["provider_id"], candidate["model"], messages, json_mode)
            except Exception as exc:
                errors.append(f"{candidate['provider_id']}/{candidate['model']}: {exc}")
        raise RuntimeError("; ".join(errors))
