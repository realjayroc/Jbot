# J-Bot desktop core

J-Bot combines its three-stage workflow, provider router, worker runtime, SQLite state, environment-backed secret access, local repository bridges, and non-destructive system diagnostics. It uses only Python's standard library.

## Run

Install Python 3.10 or later, then double-click `run_app.bat` or start the command line with `python jbot_commander.py`. `python jbot_commander.py status` displays provider and database health; `python jbot_commander.py run "your request"` runs the local intake, execution, and verification stages. `switch_model.bat` opens the model selector, and `run_tests.bat` runs the offline tests.

The router reloads `models_config.json` on each request. It supports OpenRouter free-tier models, Google AI Studio Gemini, Groq, GitHub Models, and Ollama, with configured role-based failover and automatic provider cooldowns after rate limits. Configure credentials in the launching process environment using the names in `.env.example`; J-Bot does not load `.env` files or persist credentials. Ollama must already be running locally for local fallback.

## Connect other repositories

Each target repository must implement `jroc_bridge.py` using the stable **bridge contract v1**:

```python
def get_manifest() -> dict:
    return {
        "contract_version": 1,
        "name": "repository-name",
        "workflows": ["workflow_name"],
        "description": "Optional human-readable summary",
    }

def dispatch_workflow(workflow: str, payload: dict) -> object:
    ...
```

`get_manifest()` must return a JSON-serializable object with `contract_version` exactly `1`, a non-empty `name`, and a non-empty list of unique workflow-name strings; `description` is optional and must be a string. `dispatch_workflow()` receives an advertised workflow name and a JSON object payload and must return a JSON-serializable value (object, array, string, number, boolean, or null). Raise `ValueError` for invalid arguments and an exception for execution failures; J-Bot reports any child-adapter exception, timeout, or invalid result as `BridgeError`. The J-Bot adapter's `run_task` payload is `{"request": "<non-empty task>"}` and returns the local three-stage workflow result; `health_check` accepts `{}` and returns the diagnostic report. Configure one or more repository paths in `JROC_REPO_PATHS` (path-separator-delimited), or repository-parent directories in `JROC_REPO_ROOTS`; then run `python jbot_commander.py discover`. To invoke an advertised workflow use `python jbot_commander.py dispatch <repository-name> <workflow-name> "<json-object>"`; `dispatch-all` attempts a named workflow in every discovered repo and reports per-repository failures.

Bridge adapters run as child Python processes, keeping their imports and module state separate from J-Bot. This is not an OS security sandbox: adapters still run with the current user's permissions, so configure only repositories whose code you trust. Credential-like environment variables are withheld by default; explicitly allow variables for one repository with `JROC_BRIDGE_<REPO_NAME>_ENV` (for example `JROC_BRIDGE_MY_WORKER_ENV=GITHUB_TOKEN`). Set `JROC_BRIDGE_TIMEOUT_SECONDS` to adjust the per-call timeout (default 120 seconds). No external repository paths are assumed or bundled, so cross-repository dispatch becomes available only after valid adapters are configured.

## Local state and diagnostics

Runtime state is stored in `jroc_core.db` beside the application by default; set `JROC_DB_PATH` to choose another location. It records low-sensitivity event metadata, discovered manifests, and dispatch outcomes—not prompts, model output, or credentials. `JROC_REPO_PATHS` and `JROC_REPO_ROOTS` control bridge discovery. The system auditor reports missing core files, SQLite integrity, and provider configuration. Its repair mode is diagnostic only; it does not rewrite files or modify external repositories.
