"""GTM Agent graph for LangSmith Deployment.

This is the main production agent that:
1. Handles GTM research tasks
2. Monitors for production regressions
3. Delegates to Triage Agent when issues are detected
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from deepagents import create_deep_agent

DEFAULT_MODEL = os.getenv("GTM_AGENT_MODEL", "anthropic:claude-sonnet-4-6")

SYSTEM_PROMPT = """
You are a GTM (Go-To-Market) research agent for the piggya2a-labs organization.

Your primary responsibilities:
1. Research market intelligence, competitors, and customer insights
2. Monitor for production errors and performance regressions
3. Produce structured, actionable reports

Workflow:
1. Write and maintain a todo list for non-trivial requests
2. Delegate focused fact-finding to sub-agents when helpful
3. Store intermediate drafts in files when the task is long
4. Before finalizing, critique your work for risks, gaps, and missing constraints
5. Return concise, actionable output in JSON format

Output format:
{
  "status": "success" | "error" | "regression_detected",
  "findings": [...],
  "confidence": 0.0-1.0,
  "next_actions": [...]
}

Constraints:
- Prefer concrete evidence over assumptions
- State unresolved uncertainty explicitly
- Output compact unless the user asks for depth
""".strip()


@tool
def utc_now() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


@tool
def get_deployment_info() -> dict:
    """Return current deployment metadata for context."""
    return {
        "service": "self-healing-agent",
        "version": os.getenv("DEPLOYMENT_VERSION", "unknown"),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


SUBAGENTS = [
    {
        "name": "researcher",
        "description": "Use for evidence collection and source-grounded fact finding.",
        "system_prompt": (
            "You are a focused researcher. Gather evidence, list assumptions, and "
            "report contradictions clearly. Always cite sources when possible."
        ),
        "tools": [utc_now],
    },
    {
        "name": "critic",
        "description": "Use for adversarial review of drafts and plans.",
        "system_prompt": (
            "You are a critical reviewer. Find weak logic, untested assumptions, and "
            "missing constraints. Be concise and specific."
        ),
        "tools": [utc_now],
    },
]


def _build_agent(backend=None):
    return create_deep_agent(
        model=DEFAULT_MODEL,
        tools=[utc_now, get_deployment_info],
        backend=backend,
        system_prompt=SYSTEM_PROMPT,
        subagents=SUBAGENTS,
    )


def get_agent(config: RunnableConfig):
    """Entry point for LangSmith Deployment."""
    from langgraph_sdk.runtime import ServerRuntime

    backend = ServerRuntime(config)
    return _build_agent(backend=backend)
