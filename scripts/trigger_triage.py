#!/usr/bin/env python3
"""Trigger the Triage Agent to analyze detected regressions.

This script:
1. Reads the regression report from detect_regression.py
2. Gets the git diff for the triggering commit
3. Calls the deployed Triage Agent via LangSmith API
4. Outputs a triage verdict JSON

Usage:
    python scripts/trigger_triage.py \
        --regression-report regression_report.json \
        --git-diff diff.patch \
        --deployment-url https://... \
        --output triage_verdict.json

Called by GitHub Action after regression detection.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from langgraph_sdk import get_sync_client


def main():
    parser = argparse.ArgumentParser(description="Trigger Triage Agent for regression analysis")
    parser.add_argument("--regression-report", required=True, help="Path to regression_report.json")
    parser.add_argument("--git-diff", required=True, help="Path to git diff patch file")
    parser.add_argument("--deployment-url", required=True, help="LangSmith Deployment URL for triage_agent")
    parser.add_argument("--output", default="triage_verdict.json", help="Output file path")
    args = parser.parse_args()

    # Load regression report
    report = json.loads(Path(args.regression_report).read_text())
    git_diff = Path(args.git_diff).read_text()

    if not report.get("regression_detected"):
        print("No regressions detected, skipping triage.")
        Path(args.output).write_text(json.dumps({"is_regression": False, "skipped": True}))
        sys.exit(0)

    # Build triage request
    triage_input = {
        "git_diff": git_diff[:8000],  # Truncate to avoid token limits
        "error_signatures": [r["signature"] for r in report["regressions"]],
        "baseline_error_rates": {
            r["signature"]: r["baseline_rate_per_hour"]
            for r in report["regressions"]
        },
        "post_deploy_counts": {
            r["signature"]: r["observed"]
            for r in report["regressions"]
        },
        "deploy_time": report["deploy_time"],
        "project": report["project"],
    }

    message = f"""Analyze this potential regression:

## Git Diff (recent deployment)
```diff
{triage_input['git_diff']}
```

## Detected Error Signatures
{json.dumps(triage_input['error_signatures'], indent=2)}

## Baseline Error Rates (per hour)
{json.dumps(triage_input['baseline_error_rates'], indent=2)}

## Post-Deploy Error Counts (in {report['window_hours']}h window)
{json.dumps(triage_input['post_deploy_counts'], indent=2)}

Please analyze whether these errors were caused by the code changes in the diff.
Return your verdict as JSON in the format specified in your system prompt.
"""

    print(f"Calling Triage Agent at {args.deployment_url}...")

    api_key = os.environ.get("LANGSMITH_API_KEY")
    client = get_sync_client(url=args.deployment_url, api_key=api_key)

    # Run the triage agent (stateless, no thread needed)
    response_chunks = []
    final_output = None

    try:
        for chunk in client.runs.stream(
            None,  # Threadless run
            "triage_agent",
            input={"messages": [{"role": "human", "content": message}]},
            stream_mode="updates",
        ):
            if chunk.event == "updates" and chunk.data:
                response_chunks.append(chunk.data)
                print(f"  Received chunk: {chunk.event}")

            if chunk.event == "values" and chunk.data:
                final_output = chunk.data

    except Exception as e:
        print(f"Error calling Triage Agent: {e}", file=sys.stderr)
        # Fallback: write a conservative verdict
        verdict = {
            "is_regression": True,
            "confidence": 0.5,
            "reasoning": f"Triage Agent unavailable: {e}. Manual review required.",
            "recommended_action": "monitor",
            "error": str(e),
        }
        Path(args.output).write_text(json.dumps(verdict, indent=2))
        sys.exit(0)

    # Extract verdict from final output
    verdict = {"is_regression": False, "raw_response": str(final_output)}

    if final_output:
        # Try to parse JSON from the last AI message
        messages = final_output.get("messages", [])
        for msg in reversed(messages):
            content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
            # Look for JSON block in response
            import re
            json_match = re.search(r"\{[^{}]*\"is_regression\"[^{}]*\}", content, re.DOTALL)
            if json_match:
                try:
                    verdict = json.loads(json_match.group())
                    break
                except json.JSONDecodeError:
                    pass

    Path(args.output).write_text(json.dumps(verdict, indent=2))
    print(f"\nTriage verdict written to {args.output}")
    print(f"Is regression: {verdict.get('is_regression')}")
    print(f"Confidence: {verdict.get('confidence', 'N/A')}")
    print(f"Recommended action: {verdict.get('recommended_action', 'N/A')}")

    # Exit 1 if triage confirms regression and recommends open_pr
    if verdict.get("is_regression") and verdict.get("recommended_action") == "open_pr":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
