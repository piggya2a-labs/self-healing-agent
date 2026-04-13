#!/usr/bin/env python3
"""Regression detection script.

This script:
1. Fetches error traces from LangSmith for the post-deploy window
2. Normalizes error signatures
3. Runs Poisson significance tests against the 7-day baseline
4. Outputs a JSON report of detected regressions

Usage:
    python scripts/detect_regression.py \
        --project gtm-agent \
        --window-hours 1.0 \
        --baseline-days 7 \
        --output regression_report.json

Called by GitHub Action after deployment completes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langsmith import Client
from scipy import stats


def normalize_error_signature(msg: str) -> str:
    """Normalize error message to stable signature."""
    msg = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<UUID>",
        msg,
        flags=re.IGNORECASE,
    )
    msg = re.sub(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?",
        "<TS>",
        msg,
    )
    msg = re.sub(r"\b\d+\b", "<NUM>", msg)
    return msg[:200].strip()


def fetch_error_traces(
    client: Client,
    project_name: str,
    start_time: datetime,
    end_time: datetime,
) -> dict[str, int]:
    """Fetch error traces from LangSmith and count by normalized signature."""
    error_counts: dict[str, int] = {}

    try:
        runs = client.list_runs(
            project_name=project_name,
            start_time=start_time,
            end_time=end_time,
            error=True,
        )
        for run in runs:
            if run.error:
                sig = normalize_error_signature(run.error)
                error_counts[sig] = error_counts.get(sig, 0) + 1
    except Exception as e:
        print(f"Warning: Could not fetch traces: {e}", file=sys.stderr)

    return error_counts


def run_poisson_test(
    baseline_rate_per_hour: float,
    post_deploy_count: int,
    window_hours: float,
    alpha: float = 0.05,
) -> dict:
    """Poisson significance test for error rate regression."""
    expected = baseline_rate_per_hour * window_hours
    p_value = float(stats.poisson.sf(post_deploy_count - 1, max(expected, 0.001)))
    return {
        "p_value": round(p_value, 6),
        "is_significant": p_value < alpha,
        "expected": round(expected, 2),
        "observed": post_deploy_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Detect post-deployment regressions")
    parser.add_argument("--project", required=True, help="LangSmith project name")
    parser.add_argument("--window-hours", type=float, default=1.0, help="Monitoring window in hours")
    parser.add_argument("--baseline-days", type=int, default=7, help="Baseline period in days")
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level")
    parser.add_argument("--output", default="regression_report.json", help="Output file path")
    parser.add_argument("--deploy-time", help="ISO timestamp of deployment (default: now - window)")
    args = parser.parse_args()

    client = Client()
    now = datetime.now(tz=timezone.utc)

    if args.deploy_time:
        deploy_time = datetime.fromisoformat(args.deploy_time)
        if deploy_time.tzinfo is None:
            deploy_time = deploy_time.replace(tzinfo=timezone.utc)
    else:
        deploy_time = now - timedelta(hours=args.window_hours)

    post_start = deploy_time
    post_end = deploy_time + timedelta(hours=args.window_hours)
    baseline_start = deploy_time - timedelta(days=args.baseline_days)
    baseline_end = deploy_time

    print(f"Fetching post-deploy errors: {post_start.isoformat()} → {post_end.isoformat()}")
    post_errors = fetch_error_traces(client, args.project, post_start, post_end)

    print(f"Fetching baseline errors: {baseline_start.isoformat()} → {baseline_end.isoformat()}")
    baseline_errors = fetch_error_traces(client, args.project, baseline_start, baseline_end)

    # Calculate baseline rates (errors per hour)
    baseline_hours = args.baseline_days * 24
    baseline_rates = {
        sig: count / baseline_hours for sig, count in baseline_errors.items()
    }

    # Run Poisson tests for each post-deploy error signature
    regressions = []
    all_results = []

    for sig, post_count in post_errors.items():
        baseline_rate = baseline_rates.get(sig, 0.0)
        result = run_poisson_test(baseline_rate, post_count, args.window_hours, args.alpha)
        result["signature"] = sig
        result["baseline_rate_per_hour"] = round(baseline_rate, 6)
        all_results.append(result)

        if result["is_significant"]:
            regressions.append(result)
            print(f"REGRESSION DETECTED: {sig[:80]}... (p={result['p_value']:.4f})")

    # Also flag completely new errors (no baseline)
    new_errors = [
        sig for sig in post_errors
        if sig not in baseline_errors and post_errors[sig] >= 2
    ]
    for sig in new_errors:
        if not any(r["signature"] == sig for r in regressions):
            entry = {
                "signature": sig,
                "p_value": 0.0,
                "is_significant": True,
                "expected": 0,
                "observed": post_errors[sig],
                "baseline_rate_per_hour": 0.0,
                "note": "new_error_type",
            }
            regressions.append(entry)
            print(f"NEW ERROR TYPE: {sig[:80]}... (count={post_errors[sig]})")

    report = {
        "timestamp": now.isoformat(),
        "project": args.project,
        "deploy_time": deploy_time.isoformat(),
        "window_hours": args.window_hours,
        "baseline_days": args.baseline_days,
        "regression_detected": len(regressions) > 0,
        "regression_count": len(regressions),
        "regressions": regressions,
        "all_results": all_results,
        "post_error_count": sum(post_errors.values()),
        "baseline_error_count": sum(baseline_errors.values()),
    }

    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {output_path}")
    print(f"Regressions detected: {report['regression_count']}")

    # Exit code 1 if regressions found (signals GitHub Action to continue pipeline)
    sys.exit(1 if report["regression_detected"] else 0)


if __name__ == "__main__":
    main()
