"""Central entrypoint coordinating local workflows, workers, bridges, and audits."""
from __future__ import annotations

import argparse
import json
from typing import Any

from jroc_bridge import JrocBridgeRegistry
from jroc_core import JrocCore
from omni_router import OmniRouter
from self_repair import SelfRepairAuditor
from worker_runtime import WorkerRuntime
from workflows.main_workflow import MainWorkflow


class JbotCommander:
    def __init__(self, core: JrocCore | None = None, router: OmniRouter | None = None,
                 bridge: JrocBridgeRegistry | None = None):
        self.core = core or JrocCore()
        self.router = router or OmniRouter()
        self.runtime = WorkerRuntime(self.router, self.core)
        self.bridge = bridge or JrocBridgeRegistry(self.core)
        self.auditor = SelfRepairAuditor(self.core, self.router)

    def run_local(self, request: str) -> dict[str, Any]:
        workflow = MainWorkflow(runtime=self.runtime)
        result = workflow.run(request)
        self.core.record_event("commander.workflow_completed", {"workflow": "main_workflow"})
        return result

    def discover_repositories(self, paths: list[str] | None = None) -> list[dict[str, Any]]:
        return self.bridge.discover(paths)

    def dispatch_workflow(self, repository: str, workflow: str, payload: dict[str, Any]) -> Any:
        return self.bridge.dispatch(repository, workflow, payload)

    def dispatch_all(self, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.dispatch_all(workflow, payload)

    def status(self) -> dict[str, Any]:
        return {
            "providers": self.router.providers_status(),
            "repositories": self.core.list_repositories(),
            "audit": self.auditor.audit(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="J-Bot Central Commander")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("status", help="Show provider, repository, and core health")
    commands.add_parser("discover", help="Discover repositories configured through JROC_REPO_PATHS/ROOTS")
    commands.add_parser("interactive", help="Start the J-Bot command loop")
    run_parser = commands.add_parser("run", help="Run the local three-stage workflow")
    run_parser.add_argument("request", help="Task request for the local workflow")
    dispatch_parser = commands.add_parser("dispatch", help="Trigger an advertised workflow in a discovered repo")
    dispatch_parser.add_argument("repository")
    dispatch_parser.add_argument("workflow")
    dispatch_parser.add_argument("payload", help="JSON object passed to the target bridge")
    dispatch_all_parser = commands.add_parser("dispatch-all", help="Trigger a workflow in every discovered repo")
    dispatch_all_parser.add_argument("workflow")
    dispatch_all_parser.add_argument("payload", help="JSON object passed to each target bridge")
    args = parser.parse_args()
    commander = JbotCommander()
    if args.command == "interactive":
        print("J-Bot is ready. Enter a task, 'status', or 'exit'.")
        while True:
            try:
                request = input("jbot> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if request.lower() in {"exit", "quit"}:
                break
            if not request:
                continue
            output = commander.status() if request.lower() == "status" else commander.run_local(request)
            print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    if args.command == "discover":
        output = commander.discover_repositories()
    elif args.command == "run":
        output = commander.run_local(args.request)
    elif args.command in {"dispatch", "dispatch-all"}:
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as exc:
            parser.error(f"payload must be valid JSON: {exc}")
        if not isinstance(payload, dict):
            parser.error("payload must be a JSON object")
        commander.discover_repositories()
        if args.command == "dispatch":
            output = commander.dispatch_workflow(args.repository, args.workflow, payload)
        else:
            output = commander.dispatch_all(args.workflow, payload)
    else:
        output = commander.status()
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
