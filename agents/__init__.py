"""Base agent interface routed exclusively through OmniRouter."""
from omni_router import OmniRouter


class RouterAgent:
    def __init__(self, role: str, router: OmniRouter | None = None, runtime=None):
        self.role = role
        self.router = router or OmniRouter()
        self.runtime = runtime

    def run(self, prompt: str) -> dict:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if self.runtime is not None:
            return self.runtime.run(prompt, role=self.role)
        return self.router.dispatch(prompt, role=self.role)
