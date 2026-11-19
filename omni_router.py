"""Dynamic multi-provider LLM router."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from security_vault import SecurityVault

CONFIG_PATH = Path(os.getenv("J_BOT_MODELS_CONFIG", Path(__file__).with_name("models_config.json")))


class RouterError(RuntimeError):
    """Raised when no configured provider can complete a request."""


class OmniRouter:
    def __init__(self, config_path: str | Path = CONFIG_PATH, opener=None):
        self.config_path = Path(config_path)
        self._opener = opener or urlopen
        self._lock = threading.RLock()
        self._key_indexes: dict[str, int] = {}
        self._health: dict[str, dict[str, Any]] = {}
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._vault = SecurityVault()

    def _config(self) -> dict[str, Any]:
        try:
            with self.config_path.open(encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RouterError(f"Cannot load model configuration: {exc}") from exc
        if not isinstance(config, dict) or not isinstance(config.get("providers"), dict) or not isinstance(config.get("roles"), dict):
            raise RouterError("Model configuration must define provider and role mappings")
        return config

    def _keys(self, provider: dict[str, Any]) -> list[str | None]:
        env_name = provider.get("key_env")
        if not env_name:
            return [None]
        keys = self._vault.get_key_ring(env_name)
        return keys

    def _cooling_down(self, provider: str, model: str) -> bool:
        key = (provider, model)
        with self._lock:
            until = self._cooldowns.get(key, 0)
            if until <= time.monotonic():
                self._cooldowns.pop(key, None)
                return False
            return True

    def _next_key(self, name: str, keys: list[str | None]) -> str | None:
        if keys == [None]:
            return None
        with self._lock:
            index = self._key_indexes.get(name, 0) % len(keys)
            self._key_indexes[name] = (index + 1) % len(keys)
            return keys[index]

    def _candidates(self, config: dict[str, Any], role: str, provider_override: str | None,
                    model_override: str | None) -> list[tuple[str, str]]:
        providers = config["providers"]
        if provider_override:
            if provider_override not in providers:
                raise RouterError(f"Unknown provider: {provider_override}")
            provider = providers[provider_override]
            models = [model_override] if model_override else provider.get("models", [])
            candidates = [(provider_override, model) for model in models]
        else:
            if role not in config["roles"]:
                raise RouterError(f"Unknown routing role: {role}")
            candidates = [(item["provider"], item["model"]) for item in config["roles"][role]]
            primary = config.get("primary", {})
            primary_pair = (primary.get("provider"), primary.get("model"))
            if primary_pair in candidates:
                candidates.remove(primary_pair)
                candidates.insert(0, primary_pair)
            if model_override:
                candidates = [pair for pair in candidates if pair[1] == model_override]
        return [(name, model) for name, model in candidates
                if config["providers"].get(name, {}).get("enabled", True)
                and not self._cooling_down(name, model)]

    def _call(self, provider_name: str, model: str, provider: dict[str, Any], key: str | None,
              prompt: str, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        protocol = provider.get("protocol", "openai")
        url = provider["base_url"]
        if protocol == "google":
            url = url.replace("{model}", quote(model, safe="-_."))
            if key:
                url = f"{url}?key={quote(key)}"
        settings = config.get("request", {})
        if protocol == "google":
            payload = {"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"maxOutputTokens": settings.get("max_tokens", 2048),
                                            "temperature": settings.get("temperature", 0.2)}}
        else:
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": settings.get("max_tokens", 2048),
                       "temperature": settings.get("temperature", 0.2)}
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if key and protocol != "google":
            headers["Authorization"] = f"Bearer {key}"
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        timeout = float(settings.get("timeout_seconds", 30))
        start = time.monotonic()
        with self._opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        elapsed = round((time.monotonic() - start) * 1000, 1)
        content = (data["candidates"][0]["content"]["parts"][0]["text"] if protocol == "google"
                   else data["choices"][0]["message"]["content"])
        return content, {"provider": provider_name, "model": model, "latency_ms": elapsed,
                         "usage": data.get("usage", {})}

    def dispatch(self, prompt: str, role: str = "CODE_FORGE", override_provider: str | None = None,
                 override_model: str | None = None) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        config = self._config()
        failures: list[str] = []
        for name, model in self._candidates(config, role, override_provider, override_model):
            provider = config["providers"][name]
            keys = self._keys(provider)
            if not keys:
                failures.append(f"{name}: no API key configured")
                continue
            for _ in range(len(keys)):
                key = self._next_key(name, keys)
                try:
                    content, metadata = self._call(name, model, provider, key, prompt, config)
                    with self._lock:
                        self._health[name] = {"ok": True, "latency_ms": metadata["latency_ms"], "checked_at": time.time()}
                    return {"content": content, **metadata}
                except HTTPError as exc:
                    failures.append(f"{name}/{model}: HTTP {exc.code}")
                    if exc.code in (402, 429, 503):
                        with self._lock:
                            self._cooldowns[(name, model)] = time.monotonic() + 60
                    if exc.code not in (402, 429, 500, 502, 503, 504):
                        break
                except (TimeoutError, URLError, OSError, ValueError, KeyError, IndexError) as exc:
                    failures.append(f"{name}/{model}: {type(exc).__name__}")
                    with self._lock:
                        self._cooldowns[(name, model)] = time.monotonic() + 5
                    break
            with self._lock:
                self._health[name] = {"ok": False, "error": failures[-1], "checked_at": time.time()}
        raise RouterError("All configured routes failed or are unavailable: " + "; ".join(failures))

    def hot_swap_primary(self, provider: str, model: str) -> dict[str, str]:
        config = self._config()
        if provider not in config["providers"] or model not in config["providers"][provider].get("models", []):
            raise ValueError(f"Model {model!r} is not configured for provider {provider!r}")
        config["primary"] = {"provider": provider, "model": model}
        temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.config_path)
        with self._lock:
            self._cooldowns.pop((provider, model), None)
        return dict(config["primary"])

    def providers_status(self) -> dict[str, dict[str, Any]]:
        config = self._config()
        return {name: {"enabled": provider.get("enabled", True), "configured": bool(self._keys(provider)),
                       "models": list(provider.get("models", [])), **self._health.get(name, {"ok": None, "latency_ms": None})}
                for name, provider in config["providers"].items()}


_default_router = OmniRouter()


def dispatch(prompt: str, role: str = "CODE_FORGE", override_provider: str | None = None,
             override_model: str | None = None) -> dict[str, Any]:
    return _default_router.dispatch(prompt, role, override_provider, override_model)


def hot_swap_primary(provider: str, model: str) -> dict[str, str]:
    return _default_router.hot_swap_primary(provider, model)
