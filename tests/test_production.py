"""Production router tests with mocked network responses."""
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from omni_router import OmniRouter, RouterError


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.payload


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "models_config.json"
        self.config = {
            "primary": {"provider": "a", "model": "a-model"},
            "roles": {"CODE_FORGE": [{"provider": "a", "model": "a-model"}, {"provider": "b", "model": "b-model"}]},
            "providers": {
                "a": {"enabled": True, "protocol": "openai", "base_url": "https://a.test/chat", "key_env": "A_API_KEYS", "models": ["a-model"]},
                "b": {"enabled": True, "protocol": "openai", "base_url": "https://b.test/chat", "key_env": "B_API_KEYS", "models": ["b-model"]}},
            "request": {"timeout_seconds": 1, "max_tokens": 20, "temperature": 0}}
        self.save()
        self.router = OmniRouter(self.path)
        patcher = patch.dict("os.environ", {"A_API_KEYS": "first,second", "B_API_KEYS": "third"}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def save(self):
        self.path.write_text(json.dumps(self.config), encoding="utf-8")

    def test_hot_swap_persists_and_dynamic_reload(self):
        self.router.hot_swap_primary("b", "b-model")
        self.config["roles"]["CODE_FORGE"] = [{"provider": "b", "model": "b-model"}]
        self.save()
        self.assertEqual(self.router._candidates(self.router._config(), "CODE_FORGE", None, None), [("b", "b-model")])

    def test_rotates_keys_then_failover(self):
        calls = []
        def opener(request, timeout):
            calls.append((request.full_url, request.get_header("Authorization")))
            if "a.test" in request.full_url:
                raise HTTPError(request.full_url, 429, "limited", {}, None)
            return FakeResponse({"choices": [{"message": {"content": "ok"}}], "usage": {}})
        result = OmniRouter(self.path, opener=opener).dispatch("test")
        self.assertEqual(result["provider"], "b")
        self.assertEqual(len([call for call in calls if "a.test" in call[0]]), 2)

    def test_missing_keys_fail_safely(self):
        with patch.dict("os.environ", {"A_API_KEYS": "", "B_API_KEYS": ""}):
            with self.assertRaises(RouterError):
                self.router.dispatch("test")

    def test_google_response_format(self):
        self.config["providers"] = {"google": {"enabled": True, "protocol": "google", "base_url": "https://g.test/{model}", "key_env": "GOOGLE_API_KEYS", "models": ["gemini"]}}
        self.config["roles"] = {"CODE_FORGE": [{"provider": "google", "model": "gemini"}]}
        self.config["primary"] = {"provider": "google", "model": "gemini"}
        self.save()
        with patch.dict("os.environ", {"GOOGLE_API_KEYS": "g-key"}):
            result = OmniRouter(self.path, opener=lambda request, timeout: FakeResponse({"candidates": [{"content": {"parts": [{"text": "hello"}]}}]})).dispatch("test")
        self.assertEqual(result["content"], "hello")

    def test_empty_prompt_and_invalid_hot_swap(self):
        with self.assertRaises(ValueError):
            self.router.dispatch(" ")
        with self.assertRaises(ValueError):
            self.router.hot_swap_primary("a", "not-configured")


if __name__ == "__main__":
    unittest.main()
