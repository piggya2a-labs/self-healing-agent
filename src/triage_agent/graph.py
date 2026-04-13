"""Triage Agent graph for LangSmith Deployment.

This agent analyzes production errors and determines whether they were caused
by recent code changes. It implements the regression detection logic from
LangChain's GTM Agent self-healing pipeline.

Reference: https://blog.langchain.com/production-agents-self-heal/
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from deepagents import create_deep_agent

DEFAULT_MODEL = os.getenv("TRIAGE_AGENT_MODEL", "anthropic:claude-opus-4-6")

SYSTEM_PROMPT = """
You are a production error Triage Agent. Your job is to determine whether a set of
production errors was caused by recent code changes.

## Input you receive
- `git_diff`: The unified diff of the most recent deployment
- `error_signatures`: Normalized error signatures observed after deployment
- `baseline_error_rate`: Historical error rates per signature (errors/hour)
- `post_deploy_count`: Error counts in the monitoring window after deployment

## Your analysis process
1. Classify each changed file: runtime | test | docs | ci | config
2. Only continue if runtime files were changed
3. For each new/increased error signature:
   a. Find the specific code lines in the diff that could cause this error
   b. Build a causal chain: code change → execution path → error
   c. Assign confidence (0.0-1.0) based on strength of evidence
4. Only flag as regression if you can establish a clear causal chain

## Output format (JSON)
{
  "is_regression": true | false,
  "confidence": 0.0-1.0,
  "reasoning": "step-by-step explanation",
  "affected_signatures": ["error_sig_1", ...],
  "causal_chains": [
    {
      "signature": "error_sig",
      "changed_file": "src/foo.py",
      "changed_lines": "42-58",
      "mechanism": "how the change causes the error"
    }
  ],
  "recommended_action": "open_pr" | "monitor" | "rollback" | "ignore"
}

## Critical constraints
- Do NOT flag as regression if you cannot establish a causal chain
- Environmental noise (infra issues, external API failures) should be classified as "ignore"
- If confidence < 0.7, recommend "monitor" not "open_pr"
- Be conservative: false negatives are better than false positives
""".strip()


@tool
def utc_now() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat()


@tool
def normalize_error_signature(error_message: str) -> str:
    """Normalize an error message to a stable signature by removing variable parts.

    Strips UUIDs, timestamps, numbers, and other variable content so that
    the same type of error always produces the same signature.
    """
    msg = error_message
    # Remove UUIDs
    msg = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<UUID>",
        msg,
        flags=re.IGNORECASE,
    )
    # Remove ISO timestamps
    msg = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", "<TS>", msg)
    # Remove standalone numbers
    msg = re.sub(r"\b\d+\b", "<NUM>", msg)
    # Remove file paths with line numbers
    msg = re.sub(r'File ".*?", line <NUM>', 'File "<PATH>", line <NUM>', msg)
    # Truncate to 200 chars for stability
    return msg[:200].strip()


@tool
def classify_file_type(file_path: str) -> str:
    """Classify a changed file as runtime, test, docs, ci, or config.

    This determines whether a file change could cause production regressions.
    Only 'runtime' files can cause regressions.
    """
    path = file_path.lower()

    if any(p in path for p in ["test_", "_test.", "/tests/", "/test/"]):
        return "test"
    if any(p in path for p in [".md", ".rst", ".txt", "/docs/", "readme"]):
        return "docs"
    if any(p in path for p in [".github/", "makefile", "dockerfile", ".dockerignore"]):
        return "ci"
    if any(p in path for p in ["pyproject.toml", "setup.py", "requirements", ".env", "config/"]):
        return "config"

    return "runtime"


@tool
def run_poisson_regression_test(
    baseline_rate_per_hour: float,
    post_deploy_count: int,
    window_hours: float = 1.0,
    alpha: float = 0.05,
) -> dict:
    """Run a Poisson significance test to detect error rate regression.

    Args:
        baseline_rate_per_hour: Historical error rate (errors per hour)
        post_deploy_count: Number of errors observed in the monitoring window
        window_hours: Duration of the monitoring window in hours
        alpha: Significance level (default 0.05)

    Returns:
        dict with p_value, is_significant, and interpretation
    """
    try:
        from scipy import stats

        expected = baseline_rate_per_hour * window_hours
        # One-sided Poisson test: P(X >= observed | expected)
        p_value = float(stats.poisson.sf(post_deploy_count - 1, expected))
        is_significant = p_value < alpha

        return {
            "p_value": round(p_value, 6),
            "is_significant": is_significant,
            "expected_count": round(expected, 2),
            "observed_count": post_deploy_count,
            "alpha": alpha,
            "interpretation": (
                f"Error rate is {'significantly' if is_significant else 'NOT significantly'} "
                f"elevated (p={p_value:.4f}, expected={expected:.1f}, observed={post_deploy_count})"
            ),
        }
    except ImportError:
        return {"error": "scipy not available", "is_significant": False}


def _build_agent(backend=None):
    return create_deep_agent(
        model=DEFAULT_MODEL,
        tools=[utc_now, normalize_error_signature, classify_file_type, run_poisson_regression_test],
        backend=backend,
        system_prompt=SYSTEM_PROMPT,
        subagents=[],  # Triage agent works alone, no sub-agents needed
    )


def get_agent(config: RunnableConfig):
    """Entry point for LangSmith Deployment."""
    from langgraph_sdk.runtime import ServerRuntime

    backend = ServerRuntime(config)
    return _build_agent(backend=backend)
