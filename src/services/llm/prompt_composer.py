import json
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from services.context.models import ContextBundle
else:
    ContextBundle = Any


class PromptComposer:
    """Formats context for the model without injecting policy or behavior."""

    _BLOCK_BUDGETS = {
        "system_context": 512,
        "user_input": 2048,
        "original_user_request": 2048,
        "toon_state": 4096,
        "toon_deltas": 2048,
        "session_summary": 2048,
        "scratchpad": 2048,
        "browser_state": 4096,
        "attachments": 2048,
        "capabilities_summary": 4096,
        "capability_scope": 256,
        "relevant_memory": 4096,
        "context_metadata": 4096,
        "context_evidence": 4096,
        "cognitive_frame": 2048,
        "cognitive_projection": 2048,
    }

    def __init__(self, block_budgets: Dict[str, int] | None = None):
        self.block_budgets = self._BLOCK_BUDGETS.copy()
        if block_budgets:
            self.block_budgets.update(block_budgets)
        self.last_compose_metrics: Dict[str, Any] = {}

    def update_budgets(self, block_budgets: Dict[str, int]) -> None:
        self.block_budgets.update(block_budgets)

    def compose(
        self,
        *,
        agent_name: str,
        personality: str,
        response_persona: str = "",
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
        initial_user_request: str = "",
        project_path: str,
        workspace_path: str,
        venv_python: str,
        venv_pip: str,
        browser_pages: List[Dict[str, Any]],
        session_summary: str,
        scratchpad: str,
        attachments: List[Any],
        capabilities_summary: str,
        capability_scope: str,
        relevant_memory: List[Dict[str, Any]] | None = None,
        cognitive_frame: Dict[str, Any] | None = None,
        cognitive_projection: Dict[str, Any] | None = None,
        context_bundle: ContextBundle | None = None,
        prompt_profile: str = "",
    ) -> str:
        prompt_parts: List[str] = []
        section_names: List[str] = []

        def add_section(name: str, text: str) -> None:
            value = str(text or "").strip()
            if not value:
                return
            prompt_parts.append(value)
            section_names.append(name)

        add_section("base_header", f"You are {agent_name}.")
        add_section(
            "system_context",
            self._format_system_context(
                sys_info=sys_info,
                location=location,
                channel=channel,
                user_name=user_name,
                user_language=user_language,
            ),
        )

        if user_input:
            add_section("user_input", self._section("USER INPUT", user_input, "user_input"))

        if initial_user_request:
            add_section(
                "original_user_request",
                self._section("ORIGINAL USER REQUEST", initial_user_request, "original_user_request"),
            )

        if toon_state:
            add_section("toon_state", self._section("TOON STATE", toon_state, "toon_state"))

        if toon_deltas:
            add_section(
                "toon_deltas",
                self._section(
                    "TOON DELTAS",
                    json.dumps(toon_deltas, ensure_ascii=False, separators=(",", ":")),
                    "toon_deltas",
                ),
            )

        if session_summary:
            add_section("session_summary", self._section("SESSION SUMMARY", session_summary, "session_summary"))

        if scratchpad:
            add_section("scratchpad", self._section("SCRATCHPAD", scratchpad, "scratchpad"))

        if browser_pages:
            add_section(
                "browser_state",
                self._section(
                    "BROWSER STATE",
                    json.dumps(browser_pages, ensure_ascii=False, separators=(",", ":")),
                    "browser_state",
                ),
            )

        if attachments:
            add_section(
                "attachments",
                self._section(
                    "ATTACHMENTS",
                    json.dumps(attachments, ensure_ascii=False, separators=(",", ":")),
                    "attachments",
                ),
            )

        if capabilities_summary:
            add_section(
                "capabilities_summary",
                self._section("CAPABILITIES", capabilities_summary, "capabilities_summary"),
            )

        if capability_scope:
            add_section(
                "capability_scope",
                self._section("CAPABILITY SCOPE", capability_scope, "capability_scope"),
            )

        if relevant_memory:
            add_section(
                "relevant_memory",
                self._section(
                    "RELEVANT MEMORY",
                    json.dumps(relevant_memory, ensure_ascii=False, separators=(",", ":")),
                    "relevant_memory",
                ),
            )

        if context_bundle is not None:
            metadata_block = self._format_context_bundle_metadata(context_bundle)
            if metadata_block:
                add_section("context_metadata", metadata_block)
            evidence_block = self._format_context_bundle_evidence(context_bundle)
            if evidence_block:
                add_section("context_evidence", evidence_block)

        if cognitive_frame:
            add_section(
                "cognitive_frame",
                self._section(
                    "COGNITIVE FRAME",
                    json.dumps(cognitive_frame, ensure_ascii=False, separators=(",", ":")),
                    "cognitive_frame",
                ),
            )

        if cognitive_projection:
            add_section(
                "cognitive_projection",
                self._section(
                    "COGNITIVE PROJECTION",
                    json.dumps(cognitive_projection, ensure_ascii=False, separators=(",", ":")),
                    "cognitive_projection",
                ),
            )

        prompt = "\n\n".join(prompt_parts).strip()
        self.last_compose_metrics = {
            "section_names": section_names,
            "section_count": len(section_names),
            "prompt_chars": len(prompt),
        }
        return prompt

    def _section(self, title: str, body: str, block_name: str) -> str:
        return f"[{title}]\n{self._clip_block(block_name, body)}"

    def _format_system_context(
        self,
        *,
        sys_info: Dict[str, str],
        location: str,
        channel: str,
        user_name: str,
        user_language: str,
    ) -> str:
        return (
            "[SYSTEM CONTEXT]\n"
            f"Date: {sys_info.get('date', 'unknown')} | "
            f"Time: {sys_info.get('time', 'unknown')} | "
            f"TZ: {sys_info.get('timezone', 'unknown')} | "
            f"OS: {sys_info.get('os', 'unknown')}\n"
            f"Location: {location} | Channel: {channel} | User Name: {user_name} | User Language: {user_language}"
        )

    def _format_context_bundle_metadata(self, context_bundle: ContextBundle) -> str:
        payload: Dict[str, Any] = {}
        situational_context = getattr(context_bundle, "situational_context", None)
        session_context = getattr(context_bundle, "session_context", None)
        diagnostics = getattr(context_bundle, "diagnostics", None)
        if situational_context:
            payload["situational_context"] = situational_context
        if session_context:
            payload["session_context"] = session_context
        if diagnostics is not None:
            payload["diagnostics"] = self._to_jsonable(diagnostics)
        if not payload:
            return ""
        return self._section(
            "CONTEXT METADATA",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=self._json_default),
            "context_metadata",
        )

    def _format_context_bundle_evidence(self, context_bundle: ContextBundle) -> str:
        evidence_items = list(getattr(context_bundle, "evidence_items", None) or [])
        if not evidence_items:
            return ""
        lines = ["[CONTEXT EVIDENCE]"]
        for item in evidence_items:
            item_data = self._to_jsonable(item)
            domain = str(item_data.get("domain") or "").strip()
            title = str(item_data.get("title") or "").strip()
            header = f"[EVIDENCE: {domain}]" if domain else "[EVIDENCE]"
            if title:
                header += f" {title}"
            lines.append(header)
            lines.append(
                json.dumps(item_data, ensure_ascii=False, separators=(",", ":"), default=self._json_default)
            )
        return "\n".join(lines)

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): PromptComposer._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [PromptComposer._to_jsonable(item) for item in value]
        if hasattr(value, "__dict__"):
            return {
                str(k): PromptComposer._to_jsonable(v)
                for k, v in vars(value).items()
                if not str(k).startswith("_")
            }
        return value

    @staticmethod
    def _json_default(value: Any) -> Any:
        if hasattr(value, "__dict__"):
            return PromptComposer._to_jsonable(value)
        return str(value)

    def _clip_block(self, block_name: str, text: str) -> str:
        max_chars = int(self.block_budgets.get(block_name, 2048))
        value = str(text or "").strip()
        if len(value) <= max_chars:
            return value
        clipped = value[:max_chars].rstrip()
        return f"{clipped}\n...[truncated:{block_name}]"
