"""Ops Agent graph for LangSmith Deployment.

This is the configuration management agent (Lumen's ops arm) that:
1. Reads and updates Agent System Prompts via LangSmith Management API
2. Registers new Agents into agent-gateway registry
3. Manages operational configuration changes with full audit trail

Governance constraints (v3.0):
- Every config change must originate from a GitHub Issue
- No destructive operations without explicit confirmation in task description
- All changes are logged and traceable via LangSmith Tracing
"""
from __future__ import annotations

import os
import json
import httpx
from datetime import datetime, timezone
from langchain_core.tools import tool
from deepagents import create_deep_agent

DEFAULT_MODEL = os.getenv("OPS_AGENT_MODEL", "openai:gpt-4.1-mini")

LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_ORG_ID = "4884f858-ee00-40f9-84ea-673c2cb39470"
AGENT_GATEWAY_URL = os.getenv("AGENT_GATEWAY_URL", "https://agent-gateway-production-f1f5.up.railway.app")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = "piggya2a-labs"

SYSTEM_PROMPT = """
You are Lumen's ops arm — the configuration management executor for the Adev Meta Core system.

## Identity

You are ops_agent, running inside the self-healing-agent LangSmith Deployment.
You are part of the Adev Meta Core system, which consists of:
- Frontend: GitHub Issues + GitHub Actions (task-issue-handler.yml)
- Hosting: Railway (agent-gateway, FastAPI, v0.2.0)
- Orchestration: Inngest (holds main flow state)
- Execution & Observation: LangSmith Deployment (you live here)
- Code Governance: GitHub Organization (piggya2a-labs/agent-gateway)

## Responsibilities

1. Read and update Agent System Prompts via LangSmith Prompts API
2. Register new Agents into agent-gateway registry via POST /agents/register
3. Report configuration changes back to the GitHub Issue that triggered the task

## Governance Rules

- Every action must be traceable to a GitHub Issue
- Never perform destructive operations (delete, overwrite without backup) unless explicitly stated in the task
- Always confirm what was changed in your output

## Output Format

{
  "status": "success" | "error" | "no_action_needed",
  "action_taken": "description of what was changed",
  "details": {...},
  "next_actions": []
}
""".strip()


@tool
def get_current_utc() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(tz=timezone.utc).isoformat()


@tool
def list_langsmith_prompts() -> dict:
    """List all prompts in the LangSmith workspace to find agent system prompts."""
    try:
        resp = httpx.get(
            "https://api.smith.langchain.com/api/v1/commits",
            headers={"x-api-key": LANGSMITH_API_KEY},
            params={"limit": 20},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"ok": True, "data": resp.json()}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool
def get_langsmith_prompt(prompt_name: str) -> dict:
    """
    Fetch a specific prompt from LangSmith by name.
    
    Args:
        prompt_name: The name/identifier of the prompt to fetch
    """
    try:
        resp = httpx.get(
            f"https://api.smith.langchain.com/api/v1/prompts/{prompt_name}",
            headers={"x-api-key": LANGSMITH_API_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"ok": True, "data": resp.json()}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool
def update_langsmith_prompt(prompt_name: str, new_content: str) -> dict:
    """
    Create or update a prompt in LangSmith.
    
    Args:
        prompt_name: The name/identifier of the prompt
        new_content: The new system prompt content to set
    """
    try:
        payload = {
            "manifest": {
                "lc": 1,
                "type": "constructor",
                "id": ["langchain", "prompts", "chat", "ChatPromptTemplate"],
                "kwargs": {
                    "messages": [
                        {
                            "lc": 1,
                            "type": "constructor",
                            "id": ["langchain", "prompts", "chat", "SystemMessagePromptTemplate"],
                            "kwargs": {
                                "prompt": {
                                    "lc": 1,
                                    "type": "constructor",
                                    "id": ["langchain", "prompts", "prompt", "PromptTemplate"],
                                    "kwargs": {
                                        "input_variables": [],
                                        "template": new_content,
                                        "template_format": "f-string",
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
        resp = httpx.post(
            f"https://api.smith.langchain.com/api/v1/prompts/{prompt_name}/commit",
            headers={
                "x-api-key": LANGSMITH_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return {"ok": True, "prompt_name": prompt_name, "status": "updated"}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool
def register_agent_in_gateway(
    agent_id: str,
    graph_id: str,
    description: str,
    keywords: list[str],
) -> dict:
    """
    Register a new agent in the agent-gateway registry via POST /agents/register.
    
    Args:
        agent_id: Unique identifier for the agent (e.g., "ops")
        graph_id: LangSmith graph ID (e.g., "ops_agent")
        description: Natural language description of the agent's capabilities
        keywords: List of keywords for intent matching
    """
    try:
        payload = {
            "agent_id": agent_id,
            "graph_id": graph_id,
            "description": description,
            "input_schema": ["task"],
            "output_schema": ["output", "thread_id", "run_id"],
            "keywords": keywords,
        }
        resp = httpx.post(
            f"{AGENT_GATEWAY_URL}/agents/register",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            return {"ok": True, "registered": agent_id, "response": resp.json()}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool
def list_registered_agents() -> dict:
    """List all agents currently registered in the agent-gateway."""
    try:
        resp = httpx.get(f"{AGENT_GATEWAY_URL}/agents", timeout=10)
        if resp.status_code == 200:
            return {"ok": True, "agents": resp.json()}
        return {"ok": False, "status": resp.status_code, "body": resp.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@tool
def create_github_pr(
    repo: str,
    branch_name: str,
    file_path: str,
    new_content: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
) -> dict:
    """
    Create a GitHub PR by creating a new branch, committing a file change, and opening a PR.

    Args:
        repo: Repository name within piggya2a-labs (e.g., "self-healing-agent")
        branch_name: Name of the new branch to create (e.g., "ops/update-gtm-agent-prompt")
        file_path: Path to the file to create or update (e.g., "src/gtm_agent/graph.py")
        new_content: Full new content of the file (will overwrite existing content)
        commit_message: Git commit message
        pr_title: Title of the pull request
        pr_body: Body/description of the pull request
    """
    import base64

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github+json",
    }
    base_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{repo}"

    try:
        # Step 1: Get the SHA of the latest commit on main
        resp = httpx.get(f"{base_url}/git/ref/heads/main", headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"ok": False, "step": "get_main_sha", "status": resp.status_code, "body": resp.text[:500]}
        main_sha = resp.json()["object"]["sha"]

        # Step 2: Create a new branch from main
        resp = httpx.post(
            f"{base_url}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": main_sha},
            timeout=10,
        )
        if resp.status_code not in (200, 201, 422):  # 422 = branch already exists
            return {"ok": False, "step": "create_branch", "status": resp.status_code, "body": resp.text[:500]}

        # Step 3: Get current file SHA (needed for update; None if new file)
        file_sha = None
        resp = httpx.get(
            f"{base_url}/contents/{file_path}",
            headers=headers,
            params={"ref": branch_name},
            timeout=10,
        )
        if resp.status_code == 200:
            file_sha = resp.json().get("sha")

        # Step 4: Commit the file change
        payload: dict = {
            "message": commit_message,
            "content": base64.b64encode(new_content.encode()).decode(),
            "branch": branch_name,
        }
        if file_sha:
            payload["sha"] = file_sha

        resp = httpx.put(
            f"{base_url}/contents/{file_path}",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            return {"ok": False, "step": "commit_file", "status": resp.status_code, "body": resp.text[:500]}

        # Step 5: Create the PR
        resp = httpx.post(
            f"{base_url}/pulls",
            headers=headers,
            json={
                "title": pr_title,
                "body": pr_body,
                "head": branch_name,
                "base": "main",
            },
            timeout=10,
        )
        if resp.status_code == 201:
            pr = resp.json()
            return {"ok": True, "pr_url": pr["html_url"], "pr_number": pr["number"]}
        return {"ok": False, "step": "create_pr", "status": resp.status_code, "body": resp.text[:500]}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# LangSmith Deployment requires a CompiledStateGraph exposed at module level
graph = create_deep_agent(
    model=DEFAULT_MODEL,
    tools=[
        get_current_utc,
        list_langsmith_prompts,
        get_langsmith_prompt,
        update_langsmith_prompt,
        register_agent_in_gateway,
        list_registered_agents,
        create_github_pr,
    ],
    system_prompt=SYSTEM_PROMPT,
)
