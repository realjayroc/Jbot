"""Compatibility import for the J-Bot system auditor."""
from self_repair import SelfRepairAuditor


SystemAuditor = SelfRepairAuditor

__all__ = ["SelfRepairAuditor", "SystemAuditor"]
