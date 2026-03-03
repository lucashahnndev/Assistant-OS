import asyncio
import json
import logging
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from skills.browser_control.planner import BrowserSubagent
from skills.browser_control.schemas import ToonResponse

class MockLLMManager:
    def __init__(self):
        self.chat_pool = None
        self.responses = [
            # 1. Normal Markdown
            "```json\n{\"thought\": \"Step 1\", \"action\": \"navigate\", \"args\": {\"url\": \"https://google.com\"}}\n```",
            # 2. Talkative Markdown + extra text
            "Sure, here is the JSON:\n```json\n{\"thought\": \"Searching...\", \"action\": \"type\", \"args\": {\"id\": \"1\", \"text\": \"test\"}}\n```\nHope that helps!",
            # 3. No markdown, naked JSON (requires brace scan)
            "I will click now. {\"thought\": \"Clicking\", \"action\": \"click\", \"args\": {\"id\": \"2\"}} That's it.",
            # 4. JSON with non-string response_text (Pydantic fix test)
            "{\"thought\": \"Done\", \"action\": \"answer\", \"args\": {\"text\": \"Result\"}, \"response_text\": {\"key\": \"value\"}}",
            # 5. JSON with control characters
            "{\"thought\": \"Cleaning\\x01\\x02...\", \"action\": \"wait\", \"args\": {\"seconds\": 2}}"
        ]
        self.current = 0

    async def _execute_with_router(self, pool, method, prompt, system_prompt):
        resp = self.responses[self.current % len(self.responses)]
        self.current += 1
        return resp, None

async def dry_run():
    logging.basicConfig(level=logging.INFO)
    mock_runtime = type('MockRuntime', (), {'_trace_id': 'test_trace', '_viewport': {'w':1280, 'h':720}})
    mock_llm = MockLLMManager()
    
    agent = BrowserSubagent(mock_runtime, mock_llm)
    # Mock state
    state = {
        'nodes': [], 
        'url': 'https://google.com', 
        'markers': [],
        'total_nodes': 0,
        'viewport_count': 0,
        'landmarks': []
    }
    
    print("🚀 Starting 5-cycle Dry Run...")
    for i in range(5):
        print(f"\n--- Cycle {i+1} ---")
        # Direct call to _think to test extraction
        # Note: _think is private but we can call it for testing
        result = await agent._think("test goal", state, [])
        print(f"RAW INPUT: {mock_llm.responses[i]}")
        print(f"EXTRACTED: {result}")
        
        # Verify normalization
        if 'response_text' in result:
            assert isinstance(result['response_text'], str), f"response_text should be str, got {type(result['response_text'])}"
        assert 'thought' in result, "Should have thought"
        print("✅ Cycle Success")

if __name__ == "__main__":
    asyncio.run(dry_run())
