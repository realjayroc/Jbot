"""Single-request execution layer for routed worker tasks."""
from __future__ import annotations

import time
from typing import Any

from jroc_core import JrocCore
from omni_router import OmniRouter


class WorkerRuntime:
    def __init__(self, router: OmniRouter | None = None, core: JrocCore | None = None):
        self.router = router or OmniRouter()
        self.core = core or JrocCore()

    def run(self, prompt: str, role: str = "CODE_FORGE", override_provider: str | None = None,
            override_model: str | None = None) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        start = time.monotonic()
        try:
            result = self.router.dispatch(prompt, role, override_provider, override_model)
        except Exception as exc:
            self.core.record_event("worker.failed", {"role": role, "error_type": type(exc).__name__})
            raise
        self.core.record_event(
            "worker.completed",
            {"role": role, "provider": result.get("provider"), "model": result.get("model"),
             "latency_ms": result.get("latency_ms"), "runtime_ms": round((time.monotonic() - start) * 1000, 1)},
        )
        return result
