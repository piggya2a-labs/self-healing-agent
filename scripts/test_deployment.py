"""Test script: call the deployed GTM Agent and verify trace is created."""

import asyncio
import os

from langgraph_sdk import get_client

DEPLOYMENT_URL = "https://self-healing-agent-b1df4ae7c02058668f4cea1fff4d0295.us.langgraph.app"
LANGSMITH_API_KEY = os.environ["LANGSMITH_API_KEY"]


async def main():
    client = get_client(url=DEPLOYMENT_URL, api_key=LANGSMITH_API_KEY)

    print("=== LangSmith Deployment Test ===\n")

    # 1. List available assistants
    assistants = await client.assistants.search()
    print(f"Available graphs ({len(assistants)}):")
    for a in assistants:
        print(f"  [{a['graph_id']}] {a['assistant_id']}")

    # 2. Create a thread
    thread = await client.threads.create()
    print(f"\nCreated thread: {thread['thread_id']}")

    # 3. Run GTM Agent with a simple test message
    gtm_assistant_id = next(
        a["assistant_id"] for a in assistants if a["graph_id"] == "gtm_agent"
    )
    print(f"\nRunning GTM Agent ({gtm_assistant_id})...")
    print("Input: 'What is the current UTC time? Just call the utc_now tool.'")

    run = await client.runs.create(
        thread_id=thread["thread_id"],
        assistant_id=gtm_assistant_id,
        input={
            "messages": [
                {
                    "role": "human",
                    "content": "What is the current UTC time? Just call the utc_now tool and return the result.",
                }
            ]
        },
    )
    print(f"Run created: {run['run_id']}")

    # 4. Wait for completion
    print("Waiting for run to complete...")
    result = await client.runs.join(
        thread_id=thread["thread_id"],
        run_id=run["run_id"],
    )
    print(f"Run status: {result.get('status', 'unknown')}")

    # 5. Get thread state (final output)
    state = await client.threads.get_state(thread_id=thread["thread_id"])
    messages = state.get("values", {}).get("messages", [])
    if messages:
        last_msg = messages[-1]
        print(f"\nAgent response ({last_msg.get('type', '?')}):")
        content = last_msg.get("content", "")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    print(f"  {c['text']}")
        else:
            print(f"  {content}")

    print(f"\n✅ Test complete! Check traces at:")
    print(f"   https://smith.langchain.com/o/4884f858-ee00-40f9-84ea-673c2cb39470/projects/p/self-healing-agent")


if __name__ == "__main__":
    asyncio.run(main())
