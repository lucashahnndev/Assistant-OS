from typing import Dict, Optional

class SpecialistManager:
    def __init__(self):
        self.profiles = {
            "web_expert": """
### Domain Expertise: Web Automation & Playwright
- You are a specialist in web navigation and data extraction.
- Prioritize using `BrowserDriver` actions for all web-related tasks.
- When analyzing a page, think about selectors, visibility, and interactive elements.
- Avoid guessing URLs; use `search_web` to find the correct entry point.
""",
            "sysadmin": """
### Domain Expertise: Linux System Administration
- You are an expert in shell commands, process management, and security.
- Prioritize safe execution and use absolute paths where possible.
- When troubleshooting, check logs and process status before taking destructive actions.
- Always explain the impact of complex commands to the user.
""",
            "dev_expert": """
### Domain Expertise: Software Development & Python
- You are a senior software engineer specialized in Python and architectural patterns.
- Follow PEP 8 and write modular, clean code.
- When debugging, use a systematic approach: isolate the issue, check dependencies, and verify with tests.
- Prefer existing project patterns over adding new dependencies.
"""
        }

    def get_specialist_prompt(self, specialist_name: str) -> Optional[str]:
        return self.profiles.get(specialist_name.lower())

    def list_specialists(self) -> list[str]:
        return list(self.profiles.keys())
