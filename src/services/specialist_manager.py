from typing import Dict, Optional

class SpecialistManager:
    def __init__(self):
        self.profiles = {
            "web_expert": {
                "title": "Web Automation & Playwright",
                "focus": ["browser_navigation", "data_extraction", "selector_reasoning"],
                "rules": [
                    "prefer_search_retrieval_for_non_interactive_queries",
                    "avoid_guessing_urls",
                    "confirm_interactive_state_before_completion",
                ],
            },
            "sysadmin": {
                "title": "Linux System Administration",
                "focus": ["shell_commands", "process_management", "security_safety"],
                "rules": [
                    "prefer_safe_execution",
                    "use_absolute_paths_when_possible",
                    "check_logs_before_destructive_actions",
                ],
            },
            "dev_expert": {
                "title": "Software Development & Python",
                "focus": ["python_architecture", "debugging", "tests"],
                "rules": [
                    "follow_pep8",
                    "prefer_existing_project_patterns",
                    "verify_changes_with_tests",
                ],
            },
            "calendar": {
                "title": "Calendar & Sync Management",
                "focus": ["event_scheduling", "conflict_resolution", "sync_integrity"],
                "rules": [
                    "when detecting a sync conflict (local vs external), prioritize data safety",
                    "if an external deletion is ambiguous (active local changes), ask the user instead of deleting",
                    "inform the user clearly about the divergence and offer simple choices",
                    "ensure timezones are handled consistently during resolution",
                ],
            },
        }

    def get_specialist_prompt(self, specialist_name: str) -> Optional[str]:
        profile = self.profiles.get(str(specialist_name or "").lower())
        if not isinstance(profile, dict):
            return None
        title = str(profile.get("title") or "").strip()
        focus = [str(x) for x in profile.get("focus", []) if str(x).strip()]
        rules = [str(x) for x in profile.get("rules", []) if str(x).strip()]
        focus_line = ", ".join(focus[:4]) if focus else "generalist"
        rules_lines = "\n".join(f"- {r}" for r in rules[:6]) if rules else "- apply_best_practice"
        return (
            f"### Domain Expertise: {title}\n"
            f"- Focus: {focus_line}\n"
            f"{rules_lines}"
        )

    def get_specialist_compact(self, specialist_name: str, max_items: int = 3) -> str:
        profile = self.profiles.get(str(specialist_name or "").lower())
        if not isinstance(profile, dict):
            return ""
        title = str(profile.get("title") or "").strip()
        focus = [str(x) for x in profile.get("focus", []) if str(x).strip()][:max_items]
        rules = [str(x) for x in profile.get("rules", []) if str(x).strip()][:max_items]
        head = str(specialist_name or "").strip().lower()
        return f"{head}|{title}|f:{','.join(focus)}|r:{','.join(rules)}"

    def get_specialist_ultra_compact(self, specialist_name: str, max_rules: int = 2) -> str:
        profile = self.profiles.get(str(specialist_name or "").lower())
        if not isinstance(profile, dict):
            return ""
        head = str(specialist_name or "").strip().lower()
        rules = [str(x) for x in profile.get("rules", []) if str(x).strip()][:max_rules]
        return f"{head}|r:{','.join(rules)}"

    def list_specialists(self) -> list[str]:
        return list(self.profiles.keys())
