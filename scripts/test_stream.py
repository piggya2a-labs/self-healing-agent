"""Test script: stream GTM Agent response and verify trace."""

import asyncio
import os

from langgraph_sdk import get_client

DEPLOYMENT_URL = "https://self-healing-agent-b1df4ae7c02058668f4cea1fff4d0295.us.langgraph.app"
LANGSMITH_API_KEY = os.environ["LANGSMITH_API_KEY"]


async def main():
    client = get_client(url=DEPLOYMENT_URL, api_key=LANGSMITH_API_KEY)

    print("=== GTM Agent Stream Test ===\n")

    # Create a new thread
    thread = await client.threads.create()
    print(f"Thread: {thread['thread_id']}")

    # Stream the response
    print("\nStreaming GTM Agent response...\n")
    async for chunk in client.runs.stream(
        thread_id=thread["thread_id"],
        assistant_id="e47f99de-73a2-5220-a2ac-c5d811d8a673",  # gtm_agent
        input={
            "messages": [
                {
                    "role": "human",
                    "content": "Call the utc_now tool and tell me the current UTC time. Be brief.",
                }
            ]
        },
        stream_mode="messages",
    ):
        if chunk.event == "messages/partial":
            for msg in chunk.data:
                if msg.get("type") == "ai":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                                print(c["text"], end="", flush=True)
                    elif isinstance(content, str) and content:
                        print(content, end="", flush=True)
        elif chunk.event == "error":
            print(f"\nERROR: {chunk.data}")
            break
        elif chunk.event == "end":
            print("\n\n[Stream ended]")
            break

    print(f"\n✅ Done! View trace at:")
    print(f"   https://smith.langchain.com/o/4884f858-ee00-40f9-84ea-673c2cb39470/projects/p/self-healing-agent")


if __name__ == "__main__":
    asyncio.run(main())
