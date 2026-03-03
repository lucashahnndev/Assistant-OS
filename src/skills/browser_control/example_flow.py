import asyncio
print("--- SCRIPT STARTING ---")
import json
import logging
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from src.skills.browser_control.runtime import BrowserRuntime
from src.skills.browser_control.planner import BrowserSubagent
from typing import List, Dict, Any # Added for type hints

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logging.getLogger("aosd").setLevel(logging.INFO)

# The following method is intended to be added to BrowserRuntime,
# but since we only have this file, we'll define it here as a standalone function
# and then mock its usage as if it were a method of BrowserRuntime.
# In a real scenario, this method would be added to src/skills/browser_control/runtime.py.
async def _mock_get_semantic_nodes(runtime_instance) -> List[Dict[str, Any]]:
    """
    High-efficiency semantic extraction using JS execution.
    Returns a list of interactive elements with their bounding boxes.
    """
    js_code = """
    (() => {
        const elements = Array.from(document.querySelectorAll('input, button, a, textarea, [role="button"], [role="link"], [role="checkbox"], [role="radio"]'));
        return elements.map(el => {
            const rect = el.getBoundingClientRect();
            return {
                tag: el.tagName.toLowerCase(),
                text: el.innerText || el.getAttribute('aria-label') || el.placeholder || el.value || '',
                name: el.name || '',
                role: el.getAttribute('role') || '',
                id: el.id || '',
                bbox: { x: rect.left, y: rect.top, w: rect.width, h: rect.height }
            };
        }).filter(el => el.bbox.w > 0 && el.bbox.h > 0);
    })()
    """
    res = await runtime_instance._call_cdp("Runtime.evaluate", {"expression": js_code, "returnByValue": True})
    return res.get("result", {}).get("value", [])


async def run_example():
    runtime = BrowserRuntime(headless=True)
    subagent = BrowserSubagent(runtime)
    
    try:
        # STEP 1: Launch
        await runtime.launch()
        
        # STEP 2: Navigate to Google
        print("\n--- [PLANNER] Navigating to Google ---")
        resp = await runtime.navigate("https://www.google.com")
        print(f"Status: {resp.status}")
        
        # STEP 3: Find and Type Query
        # We will simulate the planner loop identifying the search box
        print("\n--- [PLANNER] Identifying Search Input ---")
        # For Google, the search input often has name='q' or role='combobox'
        # Our planner's run_to_goal would handle this, but let's be explicit for the flow.
        
        # Navigate to search logic
        print("Intent: 'Type Assistant in search box'")
        # Get semantic nodes for analysis (High Efficiency)
        print("DEBUG: Calling runtime.get_semantic_nodes()...")
        nodes = await runtime.get_semantic_nodes()
        print(f"DEBUG: Found {len(nodes)} semantic nodes.")
        
        compressed = json.dumps(nodes)
        print("DEBUG: Procceding to analysis...")
        
        # Analyze for 'search'
        candidates = subagent.dom_analyzer.analyze(compressed, "search box")
        if candidates.candidates:
            # Match the candidate's element_id with the node in our list to get the real bbox
            # (In the analyzer, it currently returns a mock bbox)
            target_node = next((n for n in nodes if str(n.get("id")) == candidates.candidates[0].element_id or n.get("name") == "q"), None)
            
            if target_node:
                bbox = target_node["bbox"]
                print(f"Found target: {target_node['tag']} at {bbox}")
                
                # Type text (using coordinates to demonstrate full runtime capability)
                print("Action: type_text('Assistant') at coordinates")
                # Center of bbox
                cx, cy = bbox["x"] + bbox["w"]/2, bbox["y"] + bbox["h"]/2
                await runtime.click(x=cx, y=cy)
                await runtime.type_text("Assistant")
            
            # STEP 4: Submit (Danger Zone Action)
            print("\n--- [PLANNER] Submitting Search ---")
            # Enter key
            await runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "windowsVirtualKeyCode": 13})
            await runtime._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "windowsVirtualKeyCode": 13})
            
            await asyncio.sleep(2) # Wait for results
            
            print("\n--- Final Evidence ---")
            final_url = await runtime._get_current_url()
            print(f"Current URL: {final_url}")
            if "search" in final_url:
                print("SUCCESS: Google search results page reached.")
            else:
                print("FAILURE: Google search results not reached.")
                
        else:
            print("FAILURE: Could not find search input.")
            
        print("\nExample Execution Flow Completed.")
        
    except Exception as e:
        print(f"\nExample Execution Flow FAILED: {e}")
    finally:
        await runtime.close()

if __name__ == "__main__":
    asyncio.run(run_example())
