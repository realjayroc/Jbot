# J-Bot repository instructions

- Keep the desktop core dependency-free; use Python's standard library unless a feature requires otherwise.
- Route model calls through `OmniRouter` and read credentials only through environment variables. Never persist or print credentials, prompts, or model output in SQLite or diagnostics.
- Keep shared operational state in `JrocCore`; do not store secrets in the database.
- External repository adapters must expose `get_manifest()` and `dispatch_workflow(workflow, payload)`. Only load explicitly configured paths and validate every dispatched workflow against its manifest.
- Bridge adapters execute in child Python processes, not in an OS sandbox. Credential-like environment variables are withheld unless explicitly allowlisted per repository. Treat configured repositories as trusted code, keep dispatch payloads JSON-serializable, and do not claim integrations with repositories that have not been configured and discovered.
- Keep diagnostics non-destructive and add offline `unittest` coverage for behavior changes.
- Preserve `run_app.bat`, `run_tests.bat`, and `switch_model.bat` as Windows 11 double-click launchers.
