import json
from typing import Any, Dict, List


class PromptComposer:
    """Builds a provider-agnostic prompt contract for AgentIntent generation."""

    _BROWSER_KEYWORDS = (
        "browser",
        "naveg",
        "site",
        "pagina",
        "página",
        "url",
        "link",
        "youtube",
        "spotify",
        "deezer",
        "maps",
        "web",
    )

    _DEV_KEYWORDS = (
        "code",
        "codigo",
        "código",
        "script",
        "python",
        "terminal",
        "shell",
        "bash",
        "arquivo",
        "file",
        "instal",
        "dependenc",
    )

    _INTENT_SCHEMA = {
        "thought": "Internal reasoning in English",
        "plan": ["[ ] pending step", "[/] in progress", "[x] done"],
        "state_summary": {
            "goal": "Current objective",
            "cursor": "Current position",
            "done_steps": [],
            "last_outcome": "Last meaningful observation",
            "last_error": "Last error if any",
        },
        "action": "Full namespaced action id OR reply/error",
        "params": {"key": "value"},
        "task_label": "Short status label (optional)",
        "response_text": "Final user-facing text",
        "attachments": ["/absolute/path/to/file"],
    }

    _BLOCK_BUDGETS = {
        "toon_state": 2200,
        "browser_state": 2600,
        "session_summary": 1800,
        "scratchpad": 1400,
        "attachments": 1400,
        "skills_summary": 9000,
    }

    def compose(
        self,
        *,
        agent_name: str,
        personality: str,
        specialist_prompt: str,
        presentation_directive: str,
        sys_info: Dict[str, str],
        location: str,
        channel: str,
        user_name: str,
        user_language: str,
        toon_state: str,
        user_input: str,
        project_path: str,
        workspace_path: str,
        venv_python: str,
        venv_pip: str,
        browser_pages: List[Dict[str, Any]],
        session_summary: str,
        scratchpad: str,
        attachments: List[Any],
        skills_summary: str,
        skill_scope: str,
    ) -> str:
        prompt_parts: List[str] = []

        base_header = (
            f"You are {agent_name}. {personality}\n"
            f"{specialist_prompt or ''}\n"
            "You control a Linux system and must use actions to complete tasks."
        ).strip()
        prompt_parts.append(base_header)

        prompt_parts.append(
            "[LANGUAGE DIRECTIVE]\n"
            "- Think internally in English in the 'thought' field.\n"
            "- Keep action ids and params in English.\n"
            f"- Detected user language: {user_language or 'auto'}.\n"
            "- Return 'response_text' in the detected user language.\n"
            "- If detection is uncertain, follow the latest user message language.\n"
            "- Never mix languages in 'response_text'. Use one language only.\n"
            "- Forbidden: bilingual endings like Portuguese sentence + English follow-up."
        )

        prompt_parts.append(presentation_directive.strip())

        prompt_parts.append(
            "[SYSTEM CONTEXT]\n"
            f"Date: {sys_info.get('date', 'unknown')} | Time: {sys_info.get('time', 'unknown')}\n"
            f"Location: {location}\n"
            f"OS: {sys_info.get('os', 'unknown')} | User: {sys_info.get('user', 'unknown')}"
        )

        prompt_parts.append(
            "[CHANNEL CONTEXT]\n"
            f"Channel: {channel}\n"
            f"User Name: {user_name}"
        )

        prompt_parts.append(
            "[INTERNAL STATE (TOON)]\n"
            "(Summarizes your recent progress. Ignore stale steps if unrelated to the latest user message.)\n"
            f"{self._clip_block('toon_state', toon_state)}"
        )

        dynamic_sections: List[str] = []
        if self._needs_dev_context(user_input):
            dynamic_sections.append(
                "[PYTHON CONTEXT]\n"
                f"Project Path: {project_path}\n"
                f"Workspace: {workspace_path}\n"
                f"Python: {venv_python}\n"
                f"Pip: {venv_pip}"
            )

        if self._needs_browser_context(user_input, browser_pages):
            browser_state_text = json.dumps(browser_pages, indent=2, ensure_ascii=False)
            dynamic_sections.append(
                "[BROWSER STATE]\n"
                "(Only include browser automation when interaction is needed.)\n"
                f"{self._clip_block('browser_state', browser_state_text)}"
            )

        if session_summary:
            dynamic_sections.append(
                "[CONSOLIDATED SESSION SUMMARY]\n"
                f"{self._clip_block('session_summary', session_summary)}"
            )

        if scratchpad:
            dynamic_sections.append(
                "[PERSISTENT SCRATCHPAD]\n"
                f"{self._clip_block('scratchpad', scratchpad)}"
            )

        if attachments:
            attachment_text = json.dumps(attachments, indent=2, ensure_ascii=False)
            dynamic_sections.append(
                "[SESSION ATTACHMENTS]\n"
                "(Use vision/analyzer actions when needed.)\n"
                f"{self._clip_block('attachments', attachment_text)}"
            )

        if dynamic_sections:
            prompt_parts.append("[DYNAMIC CONTEXT]\n" + "\n\n".join(dynamic_sections))

        prompt_parts.append(
            "[AVAILABLE ACTIONS]\n"
            f"Scope: {skill_scope}\n"
            f"{self._clip_block('skills_summary', skills_summary or '- No actions available for this principal.')}"
        )

        prompt_parts.append(
            "[EXECUTION POLICY]\n"
            "- Always use full namespaced action ids exactly as listed.\n"
            "- Prefer discovery/read actions before destructive actions.\n"
            "- Use browser automation only when UI interaction is required.\n"
            "- If an action fails, report the failure honestly and pick an alternative.\n"
            "- Use `memory.recall` only when older context is needed.\n"
            "- In the final user reply, when appropriate, suggest one logical next step grounded in the current context/result.\n"
            "- The suggestion must be specific to the task outcome, not a generic template, and should sound natural.\n"
            "- If no meaningful next step exists, do not force a suggestion.\n"
            "- Do not challenge the user; ask supportive, practical follow-up questions only when useful."
        )

        prompt_parts.append(
            "[STRUCTURED OUTPUT CONTRACT]\n"
            "- Return exactly one JSON object (no markdown/code fence).\n"
            "- Never output text outside the JSON object.\n"
            "- Use this schema:\n"
            f"{json.dumps(self._INTENT_SCHEMA, indent=2, ensure_ascii=False)}\n"
            "- If the task is done or blocked, use `action: \"reply\"`.\n"
            "- If `action` is not `reply`, `response_text` must be a start/in-progress acknowledgment and must not claim completion/success.\n"
            "- `response_text` is user-facing prose: do not include namespaced action ids, raw JSON, or tool diagnostics.\n"
            "- For multi-step execution, do not use `reply` in intermediate steps.\n"
            "- If the same action+params fails 3 times, stop and ask for clarification."
        )

        return "\n\n".join([part for part in prompt_parts if part])

    def _needs_browser_context(self, user_input: str, browser_pages: List[Dict[str, Any]]) -> bool:
        if not browser_pages:
            return False
        if not user_input:
            return True
        return self._has_any_keyword(user_input, self._BROWSER_KEYWORDS)

    def _needs_dev_context(self, user_input: str) -> bool:
        if not user_input:
            return False
        return self._has_any_keyword(user_input, self._DEV_KEYWORDS)

    @staticmethod
    def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
        lower_text = (text or "").lower()
        return any(keyword in lower_text for keyword in keywords)

    def _clip_block(self, block_name: str, text: str) -> str:
        max_chars = self._BLOCK_BUDGETS.get(block_name, 2000)
        value = (text or "").strip()
        if len(value) <= max_chars:
            return value
        clipped = value[:max_chars].rstrip()
        return f"{clipped}\n...[truncated:{block_name}]"
