"""Three-stage workflow routed exclusively through OmniRouter."""
from agents import RouterAgent


class MainWorkflow:
    def __init__(self):
        self.intake = RouterAgent("FAST_SWARM")
        self.execution = RouterAgent("CODE_FORGE")
        self.verification = RouterAgent("LOGIC_CORE")

    def run(self, request: str) -> dict:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("request must be a non-empty string")
        intake = self.intake.run("Summarize the request and identify constraints:\n" + request)
        execution = self.execution.run("Complete this request using these constraints:\n" + intake["content"])
        verification = self.verification.run("Review for correctness and gaps:\n" + execution["content"])
        return {"intake": intake, "result": execution, "verification": verification}
