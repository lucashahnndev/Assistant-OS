import asyncio
import logging
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.skills.browser_control.runtime import BrowserRuntime

logging.basicConfig(level=logging.INFO)

async def test_handshake():
    runtime = BrowserRuntime(headless=True)
    try:
        # 1. Launch & Connect
        await runtime.launch()
        
        # 2. Navigate
        print("\n--- Navigating to Google ---")
        resp = await runtime.navigate("https://www.google.com")
        print(f"Status: {resp.status}")
        print(f"URL After: {resp.evidence_pack.url_after if resp.evidence_pack else 'N/A'}")
        
        # 3. Screenshot
        print("\n--- Capturing Screenshot ---")
        shot_resp = await runtime.screenshot()
        print(f"Status: {shot_resp.status}")
        if shot_resp.evidence_pack:
            print(f"Screenshot Ref: {shot_resp.evidence_pack.after_screenshot_ref[:50]}...")

        # 4. DOM Snapshot
        print("\n--- Capturing DOM Snapshot ---")
        dom_resp = await runtime.dom_snapshot()
        print(f"Status: {dom_resp.status}")
        
        print("\nCDP Handshake Test PASSED.")
        
    except Exception as e:
        print(f"\nCDP Handshake Test FAILED: {e}")
    finally:
        await runtime.close()

if __name__ == "__main__":
    asyncio.run(test_handshake())
