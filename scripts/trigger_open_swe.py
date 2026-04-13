#!/usr/bin/env python3
"""Trigger Open SWE to automatically fix the detected regression.

This script:
1. Reads the triage verdict
2. Creates a GitHub issue describing the regression
3. Calls Open SWE via its LangSmith Deployment API to fix the issue
4. Open SWE will open a Draft PR with the fix

Usage:
    python scripts/trigger_open_swe.py \
        --triage-verdict triage_verdict.json \
        --regression-report regression_report.json \
        --repo piggya2a-labs/self-healing-agent \
        --open-swe-url https://... \
        --output fix_result.json

Called by GitHub Action after triage confirms regression.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from github import Github


def create_github_issue(
    repo_name: str,
    triage_verdict: dict,
    regression_report: dict,
    github_token: str,
) -> tuple[int, str]:
    """Create a GitHub issue describing the regression for Open SWE to fix."""
    g = Github(github_token)
    repo = g.get_repo(repo_name)

    regressions = regression_report.get("regressions", [])
    causal_chains = triage_verdict.get("causal_chains", [])

    # Build issue body
    body = f"""## Automated Regression Report

**Detected by**: Self-Healing Agent Pipeline
**Deploy time**: {regression_report.get('deploy_time', 'unknown')}
**Confidence**: {triage_verdict.get('confidence', 'N/A')}

### Reasoning
{triage_verdict.get('reasoning', 'No reasoning provided')}

### Error Signatures
"""
    for r in regressions[:5]:  # Limit to top 5
        body += f"\n- `{r['signature'][:100]}` (observed: {r['observed']}, expected: {r['expected']})"

    if causal_chains:
        body += "\n\n### Causal Chains\n"
        for chain in causal_chains:
            body += f"\n**File**: `{chain.get('changed_file', 'unknown')}`"
            body += f"\n**Lines**: {chain.get('changed_lines', 'unknown')}"
            body += f"\n**Mechanism**: {chain.get('mechanism', 'unknown')}\n"

    body += f"""

### Instructions for Fix
1. Review the causal chains above
2. Fix the root cause in the identified files
3. Add a regression test that would catch this error
4. Ensure all existing tests still pass

**Do not** change unrelated code. Keep the fix minimal and focused.
"""

    issue = repo.create_issue(
        title=f"[Auto] Regression detected after deployment: {regression_report.get('deploy_time', 'unknown')[:10]}",
        body=body,
        labels=["bug", "regression", "automated"],
    )

    print(f"Created GitHub issue #{issue.number}: {issue.html_url}")
    return issue.number, issue.html_url


def trigger_open_swe(
    issue_number: int,
    repo_name: str,
    open_swe_url: str,
    api_key: str,
) -> dict:
    """Call Open SWE API to fix the GitHub issue."""
    from langgraph_sdk import get_sync_client

    client = get_sync_client(url=open_swe_url, api_key=api_key)

    message = f"""Fix the regression described in GitHub issue #{issue_number} in repository {repo_name}.

Please:
1. Read the issue description carefully
2. Identify the root cause based on the causal chains provided
3. Implement a minimal fix
4. Add a regression test
5. Open a Draft PR with your changes

Repository: {repo_name}
Issue: #{issue_number}
"""

    print(f"Calling Open SWE at {open_swe_url}...")

    result = {"status": "triggered", "issue_number": issue_number}

    try:
        for chunk in client.runs.stream(
            None,
            "agent",  # Open SWE uses "agent" as the graph name
            input={
                "messages": [{"role": "human", "content": message}],
                "github_repo": repo_name,
                "issue_number": issue_number,
            },
            stream_mode="updates",
        ):
            if chunk.event == "updates":
                print(f"  Open SWE: {chunk.event}")
            if chunk.event == "values" and chunk.data:
                result["final_output"] = str(chunk.data)[:500]

        result["status"] = "completed"
    except Exception as e:
        print(f"Warning: Open SWE call failed: {e}", file=sys.stderr)
        result["status"] = "error"
        result["error"] = str(e)

    return result


def main():
    parser = argparse.ArgumentParser(description="Trigger Open SWE to fix regression")
    parser.add_argument("--triage-verdict", required=True, help="Path to triage_verdict.json")
    parser.add_argument("--regression-report", required=True, help="Path to regression_report.json")
    parser.add_argument("--repo", required=True, help="GitHub repo (owner/name)")
    parser.add_argument("--open-swe-url", help="Open SWE LangSmith Deployment URL")
    parser.add_argument("--output", default="fix_result.json", help="Output file path")
    args = parser.parse_args()

    triage_verdict = json.loads(Path(args.triage_verdict).read_text())
    regression_report = json.loads(Path(args.regression_report).read_text())

    # Only proceed if triage confirms regression with open_pr recommendation
    if not triage_verdict.get("is_regression"):
        print("Triage did not confirm regression. Skipping Open SWE.")
        Path(args.output).write_text(json.dumps({"status": "skipped", "reason": "no_regression"}))
        sys.exit(0)

    if triage_verdict.get("recommended_action") not in ("open_pr", None):
        action = triage_verdict.get("recommended_action")
        print(f"Triage recommended '{action}', not 'open_pr'. Skipping Open SWE.")
        Path(args.output).write_text(json.dumps({"status": "skipped", "reason": action}))
        sys.exit(0)

    github_token = os.environ.get("GITHUB_TOKEN")
    api_key = os.environ.get("LANGSMITH_API_KEY")

    if not github_token:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    # Step 1: Create GitHub issue
    issue_number, issue_url = create_github_issue(
        args.repo, triage_verdict, regression_report, github_token
    )

    result = {
        "status": "issue_created",
        "issue_number": issue_number,
        "issue_url": issue_url,
    }

    # Step 2: Trigger Open SWE if URL is provided
    if args.open_swe_url and api_key:
        swe_result = trigger_open_swe(issue_number, args.repo, args.open_swe_url, api_key)
        result.update(swe_result)
    else:
        print("Open SWE URL not configured. Issue created, manual fix required.")
        result["note"] = "open_swe_not_configured"

    Path(args.output).write_text(json.dumps(result, indent=2))
    print(f"\nFix result written to {args.output}")
    print(f"Status: {result['status']}")
    if issue_url:
        print(f"Issue: {issue_url}")


if __name__ == "__main__":
    main()
