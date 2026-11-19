"""J-Bot bridge adapter and explicitly configured local repository discovery."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from jroc_core import JrocCore
from security_vault import SecurityVault

BRIDGE_CONTRACT_VERSION = 1


class BridgeError(RuntimeError):
    """Raised for bridge discovery, workflow, timeout, or adapter execution failures."""


def get_manifest() -> dict[str, Any]:
    """Describe J-Bot's own supported bridge workflows."""
    return {
        "name": "Jbot",
        "contract_version": BRIDGE_CONTRACT_VERSION,
        "workflows": ["run_task", "health_check"],
        "description": "J-Bot local workflow and runtime health operations",
    }


def dispatch_workflow(workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one v1 workflow and return a JSON-serializable result.

    Raises ValueError for invalid workflow/payload arguments and BridgeError for
    unknown workflow names or workflow execution failures.
    """
    if not isinstance(workflow, str) or not workflow.strip():
        raise ValueError("workflow must be a non-empty string")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if workflow == "health_check":
        from self_repair import SelfRepairAuditor

        return SelfRepairAuditor().audit()
    if workflow == "run_task":
        request = payload.get("request")
        if not isinstance(request, str) or not request.strip():
            raise ValueError("run_task requires a non-empty request")
        from jbot_commander import JbotCommander

        return JbotCommander().run_local(request)
    raise BridgeError(f"Unsupported J-Bot workflow: {workflow}")


class JrocBridgeRegistry:
    """Discover and invoke adapters from paths explicitly supplied by the operator.

    Adapter code executes as a child Python process, not in the J-Bot interpreter.
    This is process isolation, not a security sandbox; configure trusted repositories only.
    """

    def __init__(self, core: JrocCore | None = None, vault: SecurityVault | None = None):
        self.core = core or JrocCore()
        self.vault = vault or SecurityVault()
        self._lock = threading.RLock()
        self._adapters: dict[str, tuple[Path, dict[str, Any]]] = {}

    @staticmethod
    def _configured_paths() -> list[Path]:
        paths: list[Path] = []
        direct = os.getenv("JROC_REPO_PATHS", "")
        roots = os.getenv("JROC_REPO_ROOTS", "")
        for value in direct.split(os.pathsep):
            if value.strip():
                paths.append(Path(value.strip()).expanduser())
        for value in roots.split(os.pathsep):
            if value.strip():
                root = Path(value.strip()).expanduser()
                if not root.is_dir():
                    raise BridgeError(f"Configured repository root does not exist: {root}")
                paths.extend(child for child in root.iterdir() if child.is_dir())
        return paths

    @staticmethod
    def _run_adapter(path: Path, operation: str, workflow: str = "",
                     payload: dict[str, Any] | None = None,
                     secret_env_names: set[str] | None = None) -> Any:
        bridge_file = path / "jroc_bridge.py"
        if not bridge_file.is_file():
            raise BridgeError(f"Configured repository has no jroc_bridge.py: {path}")
        runner = (
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('jroc_bridge', "
            "str(__import__('pathlib').Path.cwd() / 'jroc_bridge.py'))\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "sys.modules[spec.name] = module\n"
            "spec.loader.exec_module(module)\n"
            "request = json.loads(sys.stdin.read())\n"
            "result = (module.get_manifest() if request['operation'] == 'manifest' else "
            "module.dispatch_workflow(request['workflow'], request['payload']))\n"
            "print('__JROC_RESULT__' + json.dumps(result))\n"
        )
        request = {"operation": operation, "workflow": workflow, "payload": payload or {}}
        try:
            timeout = float(os.getenv("JROC_BRIDGE_TIMEOUT_SECONDS", "120"))
            if timeout <= 0:
                raise ValueError("JROC_BRIDGE_TIMEOUT_SECONDS must be positive")
            allowlist = secret_env_names or set()
            sensitive_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "AUTH", "COOKIE")
            child_env = {
                name: value for name, value in os.environ.items()
                if name in allowlist or not any(marker in name.upper() for marker in sensitive_markers)
            }
            completed = subprocess.run(
                [sys.executable, "-c", runner],
                cwd=str(path),
                input=json.dumps(request),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=child_env,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise BridgeError(f"Bridge execution failed for {path}: {type(exc).__name__}") from exc
        if completed.returncode:
            detail = JrocBridgeRegistry._safe_error(completed.stderr)
            raise BridgeError(f"Bridge execution failed for {path}: {detail or 'adapter exited unsuccessfully'}")
        marker = "__JROC_RESULT__"
        output = next((line[len(marker):] for line in reversed(completed.stdout.splitlines())
                       if line.startswith(marker)), None)
        if output is None:
            raise BridgeError(f"Bridge returned no JSON result: {path}")
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"Bridge returned invalid JSON: {path}") from exc

    @staticmethod
    def _secret_env_allowlist(repository: str) -> set[str]:
        slug = re.sub(r"[^A-Z0-9]+", "_", repository.upper()).strip("_")
        variable = f"JROC_BRIDGE_{slug}_ENV"
        return {name.strip() for name in os.getenv(variable, "").split(os.pathsep) if name.strip()}

    @staticmethod
    def _safe_error(message: str) -> str:
        detail = SecurityVault().redact(message.strip())
        return detail[-1000:]

    @staticmethod
    def _validate_manifest(manifest: Any, path: Path) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            raise BridgeError(f"Bridge manifest must be an object: {path}")
        name = manifest.get("name")
        workflows = manifest.get("workflows")
        if not isinstance(name, str) or not name.strip():
            raise BridgeError(f"Bridge manifest must include a non-empty name: {path}")
        if manifest.get("contract_version") != BRIDGE_CONTRACT_VERSION:
            raise BridgeError(f"Bridge manifest contract_version must be {BRIDGE_CONTRACT_VERSION}: {path}")
        if not isinstance(workflows, list) or not all(isinstance(item, str) for item in workflows):
            raise BridgeError(f"Bridge manifest workflows must be a list of strings: {path}")
        workflow_names = workflows
        if not workflow_names or any(not item.strip() for item in workflow_names):
            raise BridgeError(f"Bridge manifest must include at least one valid workflow: {path}")
        if len(set(workflow_names)) != len(workflow_names):
            raise BridgeError(f"Bridge manifest workflow names must be unique: {path}")
        if "description" in manifest and not isinstance(manifest["description"], str):
            raise BridgeError(f"Bridge manifest description must be a string: {path}")
        try:
            json.dumps(manifest)
        except (TypeError, ValueError) as exc:
            raise BridgeError(f"Bridge manifest must be JSON serializable: {path}") from exc
        return manifest

    def discover(self, paths: list[str | Path] | None = None) -> list[dict[str, Any]]:
        candidates = [Path(path).expanduser() for path in paths] if paths is not None else self._configured_paths()
        own_path = Path(__file__).resolve().parent
        discovered: dict[str, tuple[Path, dict[str, Any]]] = {}
        for candidate in candidates:
            path = candidate.resolve()
            if path == own_path:
                continue
            if not path.is_dir():
                raise BridgeError(f"Configured repository path does not exist: {path}")
            try:
                manifest = self._validate_manifest(self._run_adapter(path, "manifest"), path)
            except BridgeError:
                raise
            except Exception as exc:
                raise BridgeError(f"Bridge discovery failed for {path}: {type(exc).__name__}") from exc
            name = manifest["name"].strip()
            if name in discovered:
                raise BridgeError(f"Multiple configured repositories use the bridge name {name!r}")
            discovered[name] = (path, manifest)
            self.core.upsert_repository(name, path, manifest)
        with self._lock:
            self._adapters = discovered
        return [
            {"name": name, "path": str(path), "manifest": manifest}
            for name, (path, manifest) in sorted(discovered.items())
        ]

    def dispatch(self, repository: str, workflow: str, payload: dict[str, Any]) -> Any:
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        try:
            json.dumps(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must contain only JSON-serializable values") from exc
        with self._lock:
            adapter = self._adapters.get(repository)
        if adapter is None:
            raise BridgeError(f"Repository {repository!r} is not discovered; call discover() first")
        path, manifest = adapter
        available = manifest["workflows"]
        allowed = set(available if isinstance(available, list) else available.keys())
        if workflow not in allowed:
            raise BridgeError(f"Workflow {workflow!r} is not advertised by repository {repository!r}")
        try:
            result = self._run_adapter(path, "dispatch", workflow, payload,
                                       self._secret_env_allowlist(repository))
            json.dumps(result)
        except Exception as exc:
            safe_message = self.vault.redact(str(exc))
            error = f"{type(exc).__name__}: {safe_message}"
            self.core.record_dispatch(repository, workflow, "failed", error)
            raise BridgeError(f"{repository}/{workflow} failed: {error}") from exc
        self.core.record_dispatch(repository, workflow, "completed")
        return result

    def dispatch_all(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            names = list(self._adapters)
        results: dict[str, Any] = {}
        for name in names:
            try:
                results[name] = {"status": "completed", "result": self.dispatch(name, workflow, payload)}
            except BridgeError as exc:
                results[name] = {"status": "failed", "error": str(exc)}
        return results
