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

    _ASSISTIVE_KEYWORDS = (
        "na minha tela",
        "na tela",
        "mostrar na tela",
        "mostra na tela",
        "me mostra",
        "aponta",
        "aponte",
        "destaca",
        "destaque",
        "demarca",
        "demarque",
        "circula",
        "circule",
        "desenha",
        "desenhe",
        "indicador",
        "ícone",
        "icone",
        "where is",
        "show on screen",
        "point to",
        "highlight",
        "mark on screen",
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
        "toon_deltas": 900,
        "browser_state": 2600,
        "session_summary": 1800,
        "scratchpad": 1400,
        "attachments": 1400,
        "skills_summary": 3200,
        "relevant_memory": 2500,
    }

    def __init__(self, block_budgets: Dict[str, int] = None):
        self.block_budgets = self._BLOCK_BUDGETS.copy()
        if block_budgets:
            self.block_budgets.update(block_budgets)

    def update_budgets(self, block_budgets: Dict[str, int]):
        """Updates the instance block budgets."""
        self.block_budgets.update(block_budgets)

    def compose(
        self,
        *,
        agent_name: str,
        personality: str,
        specialist_prompt: str,
        presentation_directive: str,
        instruction_pack: str = "",
        sys_info: Dict[str, str],
        location: str,
        channel: str,
        user_name: str,
        user_language: str,
        toon_state: str,
        toon_deltas: List[Dict[str, Any]],
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
        relevant_memory: List[Dict[str, Any]] = None,
    ) -> str:
        prompt_parts: List[str] = []

        base_header = (
            f"You are {agent_name}. {personality}\n"
            f"{specialist_prompt or ''}\n"
            "You control a Linux system and must use actions to complete tasks."
        ).strip()
        prompt_parts.append(base_header)

        if instruction_pack:
            prompt_parts.append("[INSTRUCTION PACK]\n" + instruction_pack)
        else:
            prompt_parts.append(
                "[LANGUAGE DIRECTIVE]\n"
                "- thought/action/params in English.\n"
                f"- response_text language: {user_language or 'auto'}.\n"
                "- Never mix languages in response_text."
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
        if toon_deltas:
            toon_deltas_text = json.dumps(toon_deltas, ensure_ascii=False, separators=(",", ":"))
            dynamic_sections.append(
                "[TOON CONTEXT DELTAS]\n"
                "(Recent compact state transitions before full memory consolidation.)\n"
                f"{self._clip_block('toon_deltas', toon_deltas_text)}"
            )

        if self._needs_dev_context(user_input):
            dynamic_sections.append(
                "[PYTHON CONTEXT]\n"
                f"Project Path: {project_path}\n"
                f"Workspace: {workspace_path}\n"
                f"Python: {venv_python}\n"
                f"Pip: {venv_pip}"
            )

        if self._needs_browser_context(user_input, browser_pages):
            browser_state_text = json.dumps(browser_pages, ensure_ascii=False, separators=(",", ":"))
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
            attachment_text = json.dumps(attachments, ensure_ascii=False, separators=(",", ":"))
            dynamic_sections.append(
                "[SESSION ATTACHMENTS]\n"
                "(Use vision/analyzer actions when needed.)\n"
                f"{self._clip_block('attachments', attachment_text)}"
            )

        if relevant_memory:
            memory_text = json.dumps(relevant_memory, ensure_ascii=False, separators=(",", ":"))
            dynamic_sections.append(
                "[RELEVANT MEMORY]\n"
                "(Selected historical context for the current turn.)\n"
                f"{self._clip_block('relevant_memory', memory_text)}"
            )

        if dynamic_sections:
            prompt_parts.append("[DYNAMIC CONTEXT]\n" + "\n\n".join(dynamic_sections))

        prompt_parts.append(
            "[AVAILABLE ACTIONS]\n"
            f"Scope: {skill_scope}\n"
            f"{self._clip_block('skills_summary', skills_summary or '- No actions available for this principal.')}"
        )

        if self._is_assistive_request(user_input):
            prompt_parts.append(
                "[ASSISTIVE MODE DIRECTIVE]\n"
                "- User asked for visual guidance on their screen.\n"
                "- Prefer `overlay.assist.highlight_target` as the primary action.\n"
                "- Use `vision.locate_screen` only as a locator step to obtain bbox for overlay.\n"
                "- Do NOT use `vision.search_screen` as final result for these requests.\n"
                "- Final outcome should be an overlay mark on target (or a structured failure with reason if target not found)."
            )

        prompt_parts.append(
            "[EXECUTION POLICY]\n"
            "- Use full namespaced action ids exactly.\n"
            "- Prefer read/discovery before destructive actions.\n"
            "- Browser actions only for real UI interaction.\n"
            "- On failure: report honestly and choose an alternative.\n"
            "- Use memory.recall only when older context is needed.\n"
            "- Never ask user to restart/send a new context; ask only for specific missing data.\n"
            "- Suggest next step only when grounded in current result."
        )

        prompt_parts.append(
            "[STRUCTURED OUTPUT CONTRACT]\n"
            "- Output exactly one JSON object (no markdown).\n"
            "- No text outside JSON.\n"
            f"- Schema: {json.dumps(self._INTENT_SCHEMA, ensure_ascii=False, separators=(',', ':'))}\n"
            "- action=reply only when done/blocked.\n"
            "- If action!=reply, response_text must be progress ack only.\n"
            "- If same action+params fails 3x, stop and ask clarification."
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

    def _is_assistive_request(self, user_input: str) -> bool:
        if not user_input:
            return False
        return self._has_any_keyword(user_input, self._ASSISTIVE_KEYWORDS)

    @staticmethod
    def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
        lower_text = (text or "").lower()
        return any(keyword in lower_text for keyword in keywords)

    def _clip_block(self, block_name: str, text: str) -> str:
        max_chars = self.block_budgets.get(block_name, 2000)
        value = (text or "").strip()
        if len(value) <= max_chars:
            return value
        clipped = value[:max_chars].rstrip()
        return f"{clipped}\n...[truncated:{block_name}]"
