# Self-Healing Agent Pipeline

A complete reproduction of [LangChain's GTM Agent self-healing pipeline](https://blog.langchain.com/production-agents-self-heal/), deployed on LangSmith Deployment.

## Architecture

```
GitHub Push → GitHub Action
       ↓
  ⏳ Wait 60 min (production stabilization)
       ↓
  🔍 Regression Detection Script
     ├── Fetch post-deploy errors from LangSmith Tracing
     ├── Normalize error signatures (UUID/timestamp stripping)
     └── Poisson significance test vs 7-day baseline
       ↓ (if regression detected)
  🤖 Triage Agent (LangSmith Deployment)
     ├── Classify changed files (runtime vs test/docs/ci)
     ├── Build causal chain: code change → error
     └── Verdict: is_regression + recommended_action
       ↓ (if confirmed + open_pr recommended)
  🔧 Open SWE (LangSmith Deployment)
     ├── Create GitHub issue with regression details
     ├── Clone repo to isolated sandbox
     ├── Write fix + regression test
     └── Open Draft PR
```

## Components

| Component | Location | Description |
|-----------|----------|-------------|
| GTM Agent | `src/gtm_agent/` | Main production agent (researcher + critic sub-agents) |
| Triage Agent | `src/triage_agent/` | Analyzes regressions, Poisson tests, causal chain analysis |
| Regression Detector | `scripts/detect_regression.py` | Fetches LangSmith traces, runs statistical tests |
| Triage Trigger | `scripts/trigger_triage.py` | Calls deployed Triage Agent via API |
| Open SWE Trigger | `scripts/trigger_open_swe.py` | Creates GitHub issue + calls Open SWE |
| GitHub Action | `.github/workflows/self-heal.yml` | Orchestrates the full pipeline |

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/piggya2a-labs/self-healing-agent
cd self-healing-agent
cp .env.example .env
# Edit .env with your API keys
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
# or with uv:
uv sync
```

### 3. Deploy to LangSmith

```bash
# Deploy both agents
LANGSMITH_API_KEY=lsv2_... langgraph deploy --name gtm-agent
```

Or via LangSmith UI:
1. Go to **Deployments** → **+ New Deployment**
2. Connect this GitHub repository
3. Set `langgraph.json` as the config file
4. Add environment variables (API keys)
5. Enable **Auto-deploy on push**

### 4. Configure GitHub Secrets

In your repository settings, add:

| Secret | Value |
|--------|-------|
| `LANGSMITH_API_KEY` | Your LangSmith API key |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GTM_AGENT_DEPLOYMENT_URL` | URL from LangSmith Deployment |
| `TRIAGE_AGENT_DEPLOYMENT_URL` | URL from LangSmith Deployment |
| `OPEN_SWE_DEPLOYMENT_URL` | URL from Open SWE deployment |

### 5. Test the pipeline

```bash
# Manual trigger via GitHub Actions UI
# Go to Actions → Self-Healing Pipeline → Run workflow
```

Or locally:

```bash
# Test regression detection (will use real LangSmith data)
python scripts/detect_regression.py \
  --project gtm-agent \
  --window-hours 1.0 \
  --output regression_report.json
```

## Key Design Decisions

### Error Normalization
Errors are normalized by stripping UUIDs, timestamps, and numbers before comparison.
This ensures `Error at 2026-04-13T10:00:00Z` and `Error at 2026-04-13T11:00:00Z`
are treated as the same error type.

### Poisson Significance Test
We use a one-sided Poisson test (α=0.05) to determine if post-deploy error rates
are significantly higher than the 7-day baseline. This minimizes false positives
from normal traffic variation.

### Conservative Triage
The Triage Agent only confirms a regression if it can establish a clear causal chain
from a specific code change to a specific error. Environmental noise is classified
as "ignore", not "regression".

### Human-in-the-Loop
Open SWE opens **Draft PRs**, not merged PRs. A human must review and merge.
The Triage Agent can also recommend "monitor" instead of "open_pr" when confidence
is below 0.7.

## References

- [LangChain GTM Agent Self-Healing Blog Post](https://blog.langchain.com/production-agents-self-heal/)
- [How We Built LangChain's GTM Agent](https://blog.langchain.com/how-we-built-langchains-gtm-agent/)
- [Open SWE GitHub](https://github.com/langchain-ai/open-swe)
- [Deep Agents Framework](https://github.com/langchain-ai/deepagents)
- [LangSmith Deployment Docs](https://docs.langchain.com/langsmith/deployment-quickstart)
