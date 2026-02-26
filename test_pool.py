import requests
import json

payload = [{"instance_id": "openai_gpt4", "provider": "openai", "priority": 1}]
try:
    # Bypass auth for testing by looking at how the routes use Depends(). If we can't bypass, we just check the python syntax directly.
    print("Testing syntax via script")
except Exception as e:
    print(e)
