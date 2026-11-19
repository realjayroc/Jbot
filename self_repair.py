"""Non-destructive self-diagnostics for the J-Bot core."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jroc_core import JrocCore
from omni_router import OmniRouter, RouterError


class SelfRepairAuditor:
    """Report core health and configuration issues without modifying source files."""

    REQUIRED_FILES = (
        "jbot_commander.py",
        "worker_runtime.py",
        "omni_router.py",
        "jroc_core.py",
        "security_vault.py",
        "jroc_bridge.py",
        "self_repair.py",
        "system_auditor.py",
    )

    def __init__(self, core: JrocCore | None = None, router: OmniRouter | None = None,
                 root: str | Path | None = None):
        self.core = core or JrocCore()
        self.router = router or OmniRouter()
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent

    def audit(self) -> dict[str, Any]:
        findings: list[dict[str, str]] = []
        for filename in self.REQUIRED_FILES:
            if not (self.root / filename).is_file():
                findings.append({"severity": "error", "check": "required_file", "message": f"Missing {filename}"})
        try:
            integrity = self.core.integrity_check()
            if integrity != "ok":
                findings.append({"severity": "error", "check": "sqlite_integrity", "message": integrity})
        except Exception as exc:
            findings.append({"severity": "error", "check": "sqlite_integrity",
                             "message": f"Database check failed: {type(exc).__name__}"})
            integrity = "error"
        try:
            providers = self.router.providers_status()
            configured = [name for name, info in providers.items() if info["configured"]]
            if not configured:
                findings.append({"severity": "warning", "check": "provider_credentials",
                                 "message": "No provider credentials are configured; local Ollama may still be available."})
        except RouterError as exc:
            findings.append({"severity": "error", "check": "router_config", "message": str(exc)})
            configured = []
        return {
            "healthy": not any(item["severity"] == "error" for item in findings),
            "database_integrity": integrity,
            "configured_providers": configured,
            "findings": findings,
            "repair_mode": "diagnostic_only",
        }
