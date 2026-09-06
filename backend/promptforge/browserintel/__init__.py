"""Browser Intelligence (Inspiration 2.0, I8): one facade, three engines.

    from promptforge import browserintel as bi
    bi.run_workflow("reddit", "search", {"query": "flux prompts"})
    bi.repair_workflow("reddit", "search")
    bi.ai_extract(url, "the post's prompt text", {"fields": {"prompt": "string"}})
    bi.availability()

Deterministic replay first, AI (Stagehand → Browser Use) only for discovery,
extraction recovery and repair — inside the domain allowlist, the read-only
policy and the daily budgets. See browserintel/policy.py for the rules.
"""
from .base import (BudgetExhausted, EngineUnavailable, ai_extract,  # noqa: F401
                   availability, check_ai_budget, discover_workflow, get_usage,
                   repair_workflow, run_workflow)
from .policy import PolicyViolation, sanitize, sanitize_text  # noqa: F401
from . import workflows  # noqa: F401
