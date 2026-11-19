"""Base agent interface routed exclusively through OmniRouter."""
from omni_router import OmniRouter


class RouterAgent:
    def __init__(self, role: str, router: OmniRouter | None = None):
        self.role = role
        self.router = router or OmniRouter()

    def run(self, prompt: str) -> dict:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        return self.router.dispatch(prompt, role=self.role)
