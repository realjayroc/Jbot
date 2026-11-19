"""Offline tests for shared state, worker orchestration, secrets, and repository bridges."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jbot_commander import JbotCommander
from jroc_bridge import BRIDGE_CONTRACT_VERSION, BridgeError, JrocBridgeRegistry, dispatch_workflow, get_manifest
from jroc_core import JrocCore
from security_vault import SecurityVault
from self_repair import SelfRepairAuditor
from worker_runtime import WorkerRuntime


class FakeRouter:
    def __init__(self):
        self.calls = []

    def dispatch(self, prompt, role="CODE_FORGE", override_provider=None, override_model=None):
        self.calls.append((prompt, role))
        return {"content": "ok", "provider": "test", "model": "test-model", "latency_ms": 1}

    def providers_status(self):
        return {"test": {"configured": True, "enabled": True, "models": ["test-model"]}}


class UnifiedCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.core = JrocCore(self.root / "state.db")
        self.addCleanup(self.tmp.cleanup)

    def test_worker_persists_metadata_without_prompt_or_response(self):
        router = FakeRouter()
        runtime = WorkerRuntime(router, self.core)
        runtime.run("sensitive prompt", role="LOGIC_CORE")
        event = self.core.recent_events()[0]
        self.assertEqual(event["event_type"], "worker.completed")
        self.assertEqual(event["details"]["role"], "LOGIC_CORE")
        stored_events = json.dumps(self.core.recent_events())
        self.assertNotIn("sensitive prompt", stored_events)
        self.assertNotIn('"content": "ok"', stored_events)

    def test_bridge_discovers_and_dispatches_only_manifest_workflows(self):
        repo = self.root / "external"
        repo.mkdir()
        (repo / "jroc_bridge.py").write_text(
            "def get_manifest():\n"
            "    return {'contract_version': 1, 'name': 'external-worker', 'workflows': ['build']}\n"
            "def dispatch_workflow(workflow, payload):\n"
            "    import os\n"
            "    return {'workflow': workflow, 'received': payload, "
            "'token_visible': bool(os.getenv('BRIDGE_TEST_TOKEN'))}\n",
            encoding="utf-8",
        )
        bridge = JrocBridgeRegistry(self.core)
        found = bridge.discover([repo])
        self.assertEqual([item["name"] for item in found], ["external-worker"])
        with patch.dict(os.environ, {"BRIDGE_TEST_TOKEN": "secret-value"}, clear=False):
            result = bridge.dispatch("external-worker", "build", {"task": "compile"})
            self.assertFalse(result["token_visible"])
            with patch.dict(os.environ, {"JROC_BRIDGE_EXTERNAL_WORKER_ENV": "BRIDGE_TEST_TOKEN"}):
                result = bridge.dispatch("external-worker", "build", {"task": "compile"})
                self.assertTrue(result["token_visible"])
        self.assertEqual(result["received"], {"task": "compile"})
        self.assertEqual(self.core.list_repositories()[0]["name"], "external-worker")
        with self.assertRaises(BridgeError):
            bridge.dispatch("external-worker", "delete_everything", {})

    def test_bridge_requires_explicit_existing_paths_and_valid_contract(self):
        bridge = JrocBridgeRegistry(self.core)
        with self.assertRaises(BridgeError):
            bridge.discover([self.root / "missing"])
        repo = self.root / "invalid"
        repo.mkdir()
        (repo / "jroc_bridge.py").write_text(
            "def get_manifest(): return {'contract_version': 1, 'name': 'invalid', 'workflows': []}\n",
            encoding="utf-8",
        )
        with self.assertRaises(BridgeError):
            bridge.discover([repo])

    def test_dispatch_all_reports_each_repository_outcome(self):
        paths = []
        for name, workflows in (("worker-one", ["build"]), ("worker-two", ["publish"])):
            repo = self.root / name
            repo.mkdir()
            (repo / "jroc_bridge.py").write_text(
                f"def get_manifest(): return {{'contract_version': 1, 'name': '{name}', "
                f"'workflows': {workflows!r}}}\n"
                "def dispatch_workflow(workflow, payload): return {'accepted': workflow}\n",
                encoding="utf-8",
            )
            paths.append(repo)
        bridge = JrocBridgeRegistry(self.core)
        bridge.discover(paths)
        results = bridge.dispatch_all("build", {})
        self.assertEqual(results["worker-one"]["status"], "completed")
        self.assertEqual(results["worker-two"]["status"], "failed")

    def test_commander_runs_existing_three_stage_workflow_through_runtime(self):
        router = FakeRouter()
        commander = JbotCommander(core=self.core, router=router)
        result = commander.run_local("do the work")
        self.assertEqual(result["result"]["content"], "ok")
        self.assertEqual([role for _prompt, role in router.calls],
                         ["FAST_SWARM", "CODE_FORGE", "LOGIC_CORE"])

    def test_secret_access_and_redaction(self):
        vault = SecurityVault()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghs_sensitive_value", "TEST_API_KEYS": "one,two"}):
            self.assertEqual(vault.get_secret("GITHUB_TOKEN"), "ghs_sensitive_value")
            self.assertEqual(vault.get_key_ring("TEST_API_KEYS"), ["one", "two"])
            self.assertEqual(vault.redact("token=ghs_sensitive_value"), "token=[REDACTED]")
        with self.assertRaises(ValueError):
            vault.get_secret("not-valid")

    def test_diagnostics_are_non_destructive_and_bridge_contract_is_exposed(self):
        report = SelfRepairAuditor(self.core, FakeRouter()).audit()
        self.assertTrue(report["healthy"])
        self.assertEqual(report["repair_mode"], "diagnostic_only")
        manifest = get_manifest()
        self.assertEqual(manifest["contract_version"], BRIDGE_CONTRACT_VERSION)
        self.assertEqual(manifest["workflows"], ["run_task", "health_check"])
        result = dispatch_workflow("health_check", {})
        self.assertIn("database_integrity", result)
        with self.assertRaises(ValueError):
            dispatch_workflow("health_check", [])
        with self.assertRaises(BridgeError):
            dispatch_workflow("missing", {})


if __name__ == "__main__":
    unittest.main()
