"""GTM Agent graph for LangSmith Deployment.

This is the main production agent that:
1. Handles GTM research tasks
2. Monitors for production regressions
3. Delegates to Triage Agent when issues are detected
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from langchain_core.tools import tool
from deepagents import create_deep_agent

DEFAULT_MODEL = os.getenv("GTM_AGENT_MODEL", "openai:gpt-4.1-mini")

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


# LangSmith Deployment requires a CompiledStateGraph exposed at module level
graph = create_deep_agent(
    model=DEFAULT_MODEL,
    tools=[utc_now, get_deployment_info],
    system_prompt=SYSTEM_PROMPT,
)
