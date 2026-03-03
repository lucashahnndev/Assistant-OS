import re
import json
from typing import Optional, Dict, Any

def clean_json(t: str) -> str:
    fixed = re.sub(r'\"thought\"\s+\"', '"thought": "', t)
    fixed = re.sub(r'\"thought\"\s+:', '"thought":?', fixed)
    fixed = re.sub(r'\"thought\":?\s+\"', '"thought": "', fixed)
    
    fixed = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', fixed)
    fixed = re.sub(r'\\x[0-9a-fA-F]{2}', '', fixed)
    fixed = re.sub(r'\\u00[0-9a-fA-F]{2}', '', fixed)

    s = fixed.find('{'); e = fixed.rfind('}')
    return fixed[s:e+1] if s != -1 and e != -1 else fixed

def extract_json(text: str) -> Optional[str]:
    if not text: return None
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fenced: return sanitize_json_str(fenced.group(1))
    start_idx = text.find('{')
    if start_idx == -1: return None
    count = 0; in_string = False; escape = False
    for i in range(start_idx, len(text)):
        char = text[i]
        if char == '"' and not escape: in_string = not in_string
        elif char == '\\' and not escape: escape = True; continue
        elif not in_string:
            if char == '{': count += 1
            elif char == '}':
                count -= 1
                if count == 0:
                    return sanitize_json_str(text[start_idx:i+1])
        escape = False
    return None

def sanitize_json_str(s: str) -> str:
    return clean_json(s)

def normalize_data(data: Dict[str, Any]):
    for field in ["thought", "step_status", "action", "response_text"]:
        if field in data:
            if data[field] is None: data[field] = ""
            elif not isinstance(data[field], str):
                data[field] = json.dumps(data[field], ensure_ascii=False) if isinstance(data[field], (dict, list)) else str(data[field])
        elif field == "response_text": data[field] = ""

# Test Cases
responses = [
    "```json\n{\"thought\": \"Step 1\", \"action\": \"navigate\"}\n```",
    "Talking... ```json {\"thought\": \"Step 2\", \"action\": \"click\"} ``` ...End",
    "Naked JSON: {\"thought\": \"Step 3\", \"action\": \"type\"} outside blocks",
    "Non-string field: {\"thought\": \"Step 4\", \"action\": \"wait\", \"response_text\": {\"status\": \"ok\"}}",
    "Control chars: {\"thought\": \"Step 5\\x01\", \"action\": \"scroll\"}"
]

print("🧪 Running Extraction & Normalization Tests...")
for i, resp in enumerate(responses):
    extracted = extract_json(resp)
    print(f"\n[Test {i+1}]")
    print(f"INPUT: {resp[:50]}...")
    if not extracted:
        print("❌ FAILED: No JSON extracted")
        continue
    print(f"EXTRACTD: {extracted}")
    data = json.loads(extracted)
    normalize_data(data)
    print(f"NORMALIZED: {data}")
    
    # Assertions
    assert isinstance(data.get('response_text', ''), str)
    assert 'thought' in data
    print("✅ SUCCESS")
