import json
from typing import Any, Dict, List, Tuple

from services.context.models import ContextBundle


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

    _TROUBLESHOOTING_KEYWORDS = (
        "error",
        "failed",
        "failure",
        "bug",
        "debug",
        "issue",
        "broken",
        "fix",
        "retry",
        "stack",
        "trace",
        "problema",
        "erro",
        "falhou",
        "falha",
        "quebrou",
        "corrigir",
        "depurar",
    )

    _INTENT_SCHEMA_COMPACT = {
        "thought": "required; English reasoning",
        "plan": ["[ ]", "[/]", "[x]"],
        "state_summary": {
            "goal": "objective",
            "cursor": "current step",
            "done_steps": ["completed"],
            "last_outcome": "last result",
            "last_error": "last error",
        },
        "action": "namespaced id | reply | error",
        "params": {
            "key": "value",
            "visualization": {
                "enabled": True,
                "mode": "data_flow|cloud_rain|neural_mesh|concept_orbit",
                "intent": "short semantic scene goal",
                "background_policy": "adaptive|locked|narrative",
            },
        },
        "task_label": "optional status",
        "response_text": "optional if action!=reply",
        "attachments": ["/absolute/path/to/file"],
    }

    _BLOCK_BUDGETS = {
        "toon_state": 2200,
        "toon_deltas": 900,
        "browser_state": 2600,
        "session_summary": 1800,
        "scratchpad": 1400,
        "attachments": 1400,
        "capabilities_summary": 2200,
        "relevant_memory": 2500,
        "context_evidence": 2200,
        "response_persona": 1500,
        "specialist_prompt": 220,
    }

    def __init__(self, block_budgets: Dict[str, int] = None):
        self.block_budgets = self._BLOCK_BUDGETS.copy()
        if block_budgets:
            self.block_budgets.update(block_budgets)
        self.last_compose_metrics: Dict[str, Any] = {}

    def update_budgets(self, block_budgets: Dict[str, int]):
        """Updates the instance block budgets."""
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
        relevant_memory: List[Dict[str, Any]] = None,
        cognitive_frame: Dict[str, Any] = None,
        cognitive_projection: Dict[str, Any] = None,
        context_bundle: ContextBundle | None = None,
        prompt_profile: str = "",
    ) -> str:
        prompt_parts: List[str] = []
        block_sizes: Dict[str, int] = {}
        reduction_audit: Dict[str, Dict[str, int]] = {}
        active_prompt_profile = str(prompt_profile or "").strip().lower() or self._infer_prompt_profile(user_input)

        def _append(name: str, text: str) -> None:
            value = str(text or "").strip()
            if not value:
                return
            prompt_parts.append(value)
            block_sizes[name] = len(value)

        base_header = (
            f"You are {agent_name}.\n"
            "Operate on a Linux system through actions."
        ).strip()
        _append("base_header", base_header)
        if specialist_prompt:
            specialist_block = self._build_specialist_block(specialist_prompt)
            _append("specialist_prompt", specialist_block)
            reduction_audit["specialist_payload"] = {
                "before_chars": len(self._legacy_specialist_block(specialist_prompt)),
                "after_chars": len(specialist_block),
                "replacement": "compact_mode_label",
                "pass": "pass4",
            }
        scoped_persona = str(response_persona or "").strip()
        include_response_persona = scoped_persona and str(capability_scope or "").strip().lower() == "principal-filtered"
        if include_response_persona:
            response_persona_block = self._build_response_persona_block(scoped_persona)
            _append(
                "response_persona",
                response_persona_block
            )
            reduction_audit["response_persona"] = {
                "before_chars": len(self._legacy_response_persona_block(scoped_persona)),
                "after_chars": len(response_persona_block),
                "replacement": "compact_mode_label",
                "pass": "pass4",
            }

        if instruction_pack:
            _append("instruction_pack", "[INSTRUCTION PACK]\n" + instruction_pack)
        else:
            _append(
                "language_directive",
                "[LANGUAGE DIRECTIVE]\n"
                f"- thought/action/params in English; response_text in {user_language or 'auto'}.\n"
                "- Keep response_text single-language."
            )
            
        state_stats = {
            "compact_state_mode_used": False,
            "scratchpad_suppressed": False,
            "scratchpad_reason": "",
            "state_redundancy_suppressed": 0,
        }

        if initial_user_request:
            _append(
                "original_user_directive",
                "[ORIGINAL USER DIRECTIVE]\n"
                f"{initial_user_request}\n"
            )

        presentation_block = self._build_presentation_block(presentation_directive)
        _append("presentation_directive", presentation_block)
        reduction_audit["presentation_payload"] = {
            "before_chars": len(str(presentation_directive or "").strip()),
            "after_chars": len(presentation_block),
            "replacement": "compact_mode_label",
            "pass": "pass4",
        }

        if cognitive_projection:
            foreground, supporting = self._build_cognitive_projection_blocks(cognitive_projection)
            if foreground:
                _append("cognitive_foreground", foreground)
            if supporting:
                _append("cognitive_supporting", supporting)
        elif cognitive_frame:
            foreground, supporting = self._build_cognitive_blocks(cognitive_frame)
            if foreground:
                _append("cognitive_foreground", foreground)
            if supporting:
                _append("cognitive_supporting", supporting)

        _append(
            "system_context",
            "[SYSTEM CONTEXT]\n"
            f"Date: {sys_info.get('date', 'unknown')} | Time: {sys_info.get('time', 'unknown')} | TZ: {sys_info.get('timezone', 'unknown')} | OS: {sys_info.get('os', 'unknown')}\n"
            f"Location: {location} | Channel: {channel} | User Name: {user_name}"
        )

        _append(
            "user_input",
            "[USER INPUT]\n"
            f"{str(user_input or '').strip()}"
        )

        toon_state_block = (
            "[TOON STATE]\n"
            "[INTERNAL STATE (TOON)]\n"
            f"{self._clip_state_block('toon_state', toon_state, active_prompt_profile, bool(context_bundle and getattr(context_bundle, 'evidence_items', None)), bool(session_summary))}"
        )
        _append("toon_state", toon_state_block)
        reduction_audit["toon_state"] = {
            "before_chars": len("[INTERNAL STATE (TOON)]\n" + self._clip_block("toon_state", toon_state)),
            "after_chars": len(toon_state_block),
            "replacement": "compact_state_mode",
            "pass": "pass5",
        }
        if bool(session_summary) or bool(context_bundle and getattr(context_bundle, "evidence_items", None)):
            state_stats["compact_state_mode_used"] = True

        if toon_deltas:
            toon_deltas_text = json.dumps(toon_deltas, ensure_ascii=False, separators=(",", ":"))
            toon_deltas_block = (
                "[TOON CONTEXT DELTAS]\n"
                f"{self._clip_state_block('toon_deltas', toon_deltas_text, active_prompt_profile, bool(context_bundle and getattr(context_bundle, 'evidence_items', None)), bool(session_summary))}"
            )
            _append("toon_deltas", toon_deltas_block)
            reduction_audit["toon_deltas"] = {
                "before_chars": len("[TOON CONTEXT DELTAS]\n" + self._clip_block("toon_deltas", toon_deltas_text)),
                "after_chars": len(toon_deltas_block),
                "replacement": "compact_state_mode",
                "pass": "pass5",
            }
            state_stats["compact_state_mode_used"] = True

        if self._needs_dev_context(user_input):
            _append(
                "python_context",
                "[PYTHON CONTEXT]\n"
                f"Project Path: {project_path}\n"
                f"Workspace: {workspace_path}\n"
                f"Python: {venv_python}\n"
                f"Pip: {venv_pip}"
            )

        if self._needs_browser_context(user_input, browser_pages):
            browser_state_text = json.dumps(browser_pages, ensure_ascii=False, separators=(",", ":"))
            _append(
                "browser_state",
                "[BROWSER STATE]\n"
                f"{self._clip_block('browser_state', browser_state_text)}"
            )

        if session_summary:
            session_summary_block = (
                "[SESSION SUMMARY]\n"
                f"{self._clip_state_block('session_summary', session_summary, active_prompt_profile, bool(context_bundle and getattr(context_bundle, 'evidence_items', None)), True)}"
            )
            _append("session_summary", session_summary_block)
            reduction_audit["session_summary"] = {
                "before_chars": len("[SESSION SUMMARY]\n" + self._clip_block("session_summary", session_summary)),
                "after_chars": len(session_summary_block),
                "replacement": "compact_state_mode",
                "pass": "pass5",
            }
            state_stats["compact_state_mode_used"] = True

        include_scratchpad = bool(scratchpad)
        if scratchpad and session_summary and self._state_text_is_redundant(session_summary, scratchpad):
            include_scratchpad = False
            state_stats["scratchpad_suppressed"] = True
            state_stats["scratchpad_reason"] = "redundant_with_summary"
            state_stats["state_redundancy_suppressed"] += 1
        elif scratchpad and active_prompt_profile == "conversational" and len(str(scratchpad or "").strip()) < 80:
            include_scratchpad = False
            state_stats["scratchpad_suppressed"] = True
            state_stats["scratchpad_reason"] = "light_conversational_turn"
            state_stats["state_redundancy_suppressed"] += 1

        if include_scratchpad:
            scratchpad_block = (
                "[SCRATCHPAD]\n"
                f"{self._clip_state_block('scratchpad', scratchpad, active_prompt_profile, bool(context_bundle and getattr(context_bundle, 'evidence_items', None)), bool(session_summary))}"
            )
            _append("scratchpad", scratchpad_block)
            reduction_audit["scratchpad"] = {
                "before_chars": len("[SCRATCHPAD]\n" + self._clip_block("scratchpad", scratchpad)),
                "after_chars": len(scratchpad_block),
                "replacement": "compact_state_mode",
                "pass": "pass5",
            }
            state_stats["compact_state_mode_used"] = True
        elif scratchpad:
            reduction_audit["scratchpad"] = {
                "before_chars": len("[SCRATCHPAD]\n" + self._clip_block("scratchpad", scratchpad)),
                "after_chars": 0,
                "replacement": "redundant_state_suppressed",
                "pass": "pass5",
            }

        if attachments:
            attachment_text = json.dumps(attachments, ensure_ascii=False, separators=(",", ":"))
            _append(
                "attachments",
                "[ATTACHMENTS]\n"
                f"{self._clip_block('attachments', attachment_text)}"
            )

        if relevant_memory:
            memory_text = json.dumps(relevant_memory, ensure_ascii=False, separators=(",", ":"))
            _append(
                "relevant_memory",
                "[RELEVANT MEMORY]\n"
                f"{self._clip_block('relevant_memory', memory_text)}"
            )

        evidence_text, evidence_stats = self._prepare_context_evidence(context_bundle, active_prompt_profile)
        if evidence_text:
            evidence_block = (
                "[BROKER EVIDENCE]\n"
                f"{self._clip_state_block('context_evidence', evidence_text, active_prompt_profile, True, bool(session_summary))}"
            )
            _append("context_evidence", evidence_block)
            reduction_audit["context_evidence"] = {
                "before_chars": len("[BROKER EVIDENCE]\n" + self._legacy_format_context_evidence(context_bundle)),
                "after_chars": len(evidence_block),
                "replacement": "best_of_domain_selection",
                "pass": "pass5",
            }

        broker_anchor = self._build_broker_anchor(context_bundle)
        if broker_anchor:
            _append("broker_guidance", broker_anchor)

        actions_block = (
            "[DISCOVERY]\n"
            f"s={capability_scope}\n"
            f"{self._clip_block('capabilities_summary', capabilities_summary or '- No actions available for this principal.')}"
        )
        _append("actions", actions_block)
        reduction_audit["discovery_anchor"] = {
            "before_chars": len(self._legacy_actions_block(capability_scope, capabilities_summary)),
            "after_chars": len(actions_block),
            "replacement": "single_discovery_entrypoint",
            "pass": "pass4",
        }
        legacy_browser_block = self._legacy_browser_intent_classes_block(capabilities_summary)
        reduction_audit["browser_intent_classes"] = {
            "before_chars": len(legacy_browser_block),
            "after_chars": 0,
        }

        if self._is_assistive_request(user_input):
            assistive_block = self._build_assistive_directive()
            _append("assistive_mode", assistive_block)
            reduction_audit["assistive_mode"] = {
                "before_chars": len(self._legacy_assistive_directive()),
                "after_chars": len(assistive_block),
                "replacement": "short_anchor",
            }
        else:
            reduction_audit["assistive_mode"] = {
                "before_chars": 0,
                "after_chars": 0,
                "replacement": "none",
            }

        execution_policy_block = self._build_execution_policy()
        _append("execution_policy", execution_policy_block)
        reduction_audit["execution_policy"] = {
            "before_chars": len(self._legacy_execution_policy()),
            "after_chars": len(execution_policy_block),
            "replacement": "broker_anchor_and_kernel",
        }
        reduction_audit["browser_intent_classes"]["replacement"] = "instruction_pack_only"

        structured_contract = self._build_structured_output_contract()
        _append("structured_output_contract", structured_contract)
        reduction_audit["structured_output_contract"] = {
            "before_chars": len(self._legacy_structured_output_contract()),
            "after_chars": len(structured_contract),
            "replacement": "compact_schema_contract",
            "pass": "pass4",
        }

        prompt = "\n\n".join([part for part in prompt_parts if part])
        self.last_compose_metrics = self._build_prompt_metrics(
            prompt=prompt,
            block_sizes=block_sizes,
            reduction_audit=reduction_audit,
            context_bundle=context_bundle,
            prompt_profile=active_prompt_profile,
            discovery_mode=self._extract_discovery_mode(capabilities_summary),
            state_stats=state_stats,
            evidence_stats=evidence_stats,
        )
        return prompt

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

    @staticmethod
    def _build_broker_anchor(context_bundle: ContextBundle | None) -> str:
        has_evidence = bool(context_bundle and getattr(context_bundle, "evidence_items", None))
        return PromptComposer._broker_anchor_text(has_evidence)

    @staticmethod
    def _broker_anchor_text(has_evidence: bool) -> str:
        if has_evidence:
            return (
                "[BROKER GUIDANCE]\n"
                "- Use broker evidence for capability semantics, procedures, examples, policies, experience, and reference knowledge when relevant.\n"
                "- If evidence is partial, combine it with live state and action availability without treating the evidence as absolute."
            )
        return (
            "[BROKER GUIDANCE]\n"
            "- If broker evidence is absent, rely on live state, session context, and action availability as the primary signal."
        )

    def _build_assistive_directive(self) -> str:
        rules = [
            "Use vision and overlay tools when the task depends on what is on screen; do not claim lack of screen visibility when those tools are available.",
            "Prefer `overlay.assist.highlight_target` for marking and `vision.locate_screen` for bbox lookup.",
            "Use the UI target as `label` and end with an overlay result or a grounded failure.",
        ]
        return "[ASSISTIVE MODE DIRECTIVE]\n" + "\n".join(f"- {rule}" for rule in rules)

    @staticmethod
    def _legacy_assistive_directive() -> str:
        return (
            "[ASSISTIVE MODE DIRECTIVE]\n"
            "- Use vision capabilities via tools when available; avoid framing the task as if screen visibility were unavailable.\n"
            "- User asked for visual guidance on their screen.\n"
            "- Prefer `overlay.assist.highlight_target` when visual marking is needed.\n"
            "- Prefer `vision.locate_screen` as a locator step when you need bbox for overlay.\n"
            "- Avoid using `vision.search_screen` as final result for these requests.\n"
            "- Extract visual style when explicit: mark_type (arrow/rect/circle/focus_corners), color, pulse.\n"
            "- `label` must be the UI target only (never retry/meta phrases like 'tenta novamente').\n"
            "- Final outcome should be an overlay mark on target (or a structured failure with reason if target not found)."
        )

    def _build_execution_policy(self) -> str:
        rules = [
            "CRITICAL CAPABILITY RULE: rely on the available tools for screen observation, capture, browser control, and system interaction instead of claiming a lack of visibility or a text-only limitation.",
            "Use exact namespaced action ids; prefer discovery before execution and never invent a tool that was not returned by discovery.",
            "Use browser actions only for explicit browser/UI interaction or when a page must truly be manipulated or verified visually.",
            "Ask at most one concise clarification only if completion criteria are truly ambiguous.",
            "On failure, be honest, choose a grounded alternative, and avoid retry loops.",
            "When the user asks for a visual display, 3D scene, particle simulation, server/data flow visualization, dynamic charts, particle compositor, or drawing, prefer `reply` with a rich conceptual scene description when that preserves the task intent better than a direct tool call.",
            "When the project exposes a dedicated visual subagent and visualization would help, include `params.visualization` on the `reply` action with:",
            "  - `enabled`: true",
            "  - `mode`: one of `data_flow`, `cloud_rain`, `neural_mesh`, `concept_orbit`",
            "  - `intent`: short semantic description of what should appear",
            "  - `background_policy`: `adaptive`, `locked`, or `narrative`",
            "Use this visual delegation for spatial, structural, process-oriented, or metaphorical explanations. Do not use it for greetings or trivial chat.",
            "Prefer the built-in 3D particle engine when it is a better fit than an external drawing tool, and keep the plan grounded rather than forcing an error outcome.",
        ]
        return "[EXECUTION POLICY]\n" + "\n".join(f"- {rule}" for rule in rules)

    def _build_response_persona_block(self, scoped_persona: str) -> str:
        return (
            "[RESPONSE PERSONA]\n"
            "- Apply only to `response_text`; never to `thought/plan/action/params/state_summary`.\n"
            f"{self._clip_block('response_persona', scoped_persona)}"
        )

    def _build_specialist_block(self, specialist_prompt: str) -> str:
        return (
            "[SPECIALIST]\n"
            f"{self._clip_block('specialist_prompt', specialist_prompt)}"
        )

    @staticmethod
    def _build_presentation_block(presentation_directive: str) -> str:
        lines = []
        for raw_line in str(presentation_directive or "").splitlines():
            cleaned = raw_line.strip()
            if not cleaned or cleaned == "[PRESENTATION DIRECTIVE]":
                continue
            cleaned = cleaned.lstrip("-").strip()
            lowered = cleaned.lower()
            if "voice mode" in lowered:
                lines.append("mode=voice_plain")
            elif "plain text only" in lowered:
                lines.append("mode=plain")
            elif "markdown preferred" in lowered:
                lines.append("mode=markdown")
            elif "show concrete result snippets" in lowered:
                lines.append("result=concrete")
            elif "voice interaction" in lowered and "response_text" not in lowered:
                lines.append("reply=brief")
            elif "applies to final user response" in lowered or "response_text" in lowered:
                lines.append("brevity=response_text_only")
            elif "always use their role" in lowered:
                lines.append("workers=role_names")
            elif "sole voice of the system" in lowered:
                lines.append("voice=single_user_facing")
            elif "[critical: degraded capabilities]" in lowered:
                lines.append("degraded=present")
            elif "tool/worker" in lowered and "currently" in lowered:
                lines.append(cleaned.replace("Tool/Worker ", "tool=").replace(" is currently ", ":"))
            elif "operate in degraded mode" in lowered:
                lines.append("degraded=avoid_unhealthy_tools")
            else:
                lines.append(cleaned)
        
        # Add global rule for conversational tool results
        lines.append("tool_results=natural_language_summary (never output raw JSON or robotic lists for weather/health/etc in response_text)")

        deduped = []
        seen = set()
        for line in lines:
            if line and line not in seen:
                deduped.append(line)
                seen.add(line)
        return "[PRESENTATION]\n" + "\n".join(f"- {line}" for line in deduped[:8])

    def _build_structured_output_contract(self) -> str:
        return (
            "[STRUCTURED OUTPUT CONTRACT]\n"
            "- One JSON object only; no markdown or extra text.\n"
            f"- Schema: {json.dumps(self._INTENT_SCHEMA_COMPACT, ensure_ascii=False, separators=(',', ':'))}\n"
            "- `reply` = answer/clarify/wait; otherwise use a namespaced action id or `error`.\n"
            "- If action!=reply, keep `response_text` optional and brief.\n"
            "- Clarifications: single-turn and actionable. Same action+params fails 3x => clarify."
        )

    @staticmethod
    def _legacy_execution_policy() -> str:
        return (
            "[EXECUTION POLICY]\n"
            "- Use full namespaced action ids.\n"
            "- Prefer discovery before execution and never invent a tool that was not returned by discovery.\n"
            "- Browser actions only for real UI interaction.\n"
            "- On failure: report honestly and choose an alternative.\n"
            "- Use memory.recall only when older context is needed.\n"
            "- Avoid asking the user to restart or send a new context; ask only for specific missing data.\n"
            "- Suggest next step only when grounded in current result.\n"
            "- Stay proactively helpful without over-asking:\n"
            "  - If user request is ambiguous (especially completion criteria), ask one concise clarification in persona.\n"
            "  - If request is clear, execute directly and avoid unnecessary clarification.\n"
            "  - After a meaningful result, propose 1-2 concrete continuity actions.\n"
            "- Artifact mindset:\n"
            "  - If user asks for report/summary/audit, prefer producing a structured deliverable when tools allow (e.g., markdown/json file) and offer it naturally.\n"
            "  - If user did not explicitly ask for a file but the task benefits from one, offer the option in one sentence.\n"
            "  - Never fabricate files; only claim artifacts that were actually produced by actions.\n"
            "- Agentic clarification policy (no hardcoded templates):\n"
            "  - If task completion expectation is ambiguous, you may choose `reply` first to clarify in your persona/tone.\n"
            "  - Keep clarification to one concise question and preserve user goal semantics.\n"
            "  - After user clarifies, proceed with `browser.control.run` and include `params.completion_mode` when applicable:\n"
            "    `execution_only` (execute in browser) or `artifact_report` (execute + return structured findings)."
        )

    @staticmethod
    def _legacy_browser_intent_classes_block(capabilities_summary: str) -> str:
        return ""

    def _legacy_response_persona_block(self, scoped_persona: str) -> str:
        return (
            "[RESPONSE PERSONA]\n"
            "- Apply this style ONLY to `response_text` (user-facing output).\n"
            "- Never apply persona/tone to `thought`, `plan`, `action`, `params`, or `state_summary`.\n"
            f"{self._clip_block('response_persona', scoped_persona)}"
        )

    @staticmethod
    def _legacy_specialist_block(specialist_prompt: str) -> str:
        return str(specialist_prompt or "").strip()

    def _legacy_actions_block(self, capability_scope: str, capabilities_summary: str) -> str:
        return (
            "[DISCOVERY]\n"
            f"scope={capability_scope}\n"
            f"{self._clip_block('capabilities_summary', capabilities_summary or '- No actions available for this principal.')}"
        )

    def _legacy_structured_output_contract(self) -> str:
        return (
            "[STRUCTURED OUTPUT CONTRACT]\n"
            "- Output exactly one JSON object (no markdown).\n"
            "- No text outside JSON.\n"
            f"- Schema: {json.dumps(self._INTENT_SCHEMA_COMPACT, ensure_ascii=False, separators=(',', ':'))}\n"
            "- Use `reply` for conversational answers, clarification, or when no tool action is needed.\n"
            "- If action!=reply, response_text is optional and should be a short execution ack.\n"
            "- If replying with a clarifying question, keep it single-turn and actionable.\n"
            "- If same action+params fails 3x, stop and ask clarification."
        )

    def _build_prompt_metrics(
        self,
        *,
        prompt: str,
        block_sizes: Dict[str, int],
        reduction_audit: Dict[str, Dict[str, int]],
        context_bundle: ContextBundle | None,
        prompt_profile: str,
        discovery_mode: str,
        state_stats: Dict[str, Any],
        evidence_stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        before_total = len(prompt)
        before_pass4_total = len(prompt)
        before_pass5_total = len(prompt)
        for item in reduction_audit.values():
            before_total += max(0, int(item.get("before_chars", 0)) - int(item.get("after_chars", 0)))
            if str(item.get("pass") or "").strip() == "pass4":
                before_pass4_total += max(0, int(item.get("before_chars", 0)) - int(item.get("after_chars", 0)))
            if str(item.get("pass") or "").strip() == "pass5":
                before_pass5_total += max(0, int(item.get("before_chars", 0)) - int(item.get("after_chars", 0)))
        evidence_items = list(getattr(context_bundle, "evidence_items", None) or [])
        evidence_domains = sorted({item.domain for item in evidence_items})
        retained_blocks = dict(sorted(block_sizes.items(), key=lambda row: row[1], reverse=True))
        largest_blocks = list(retained_blocks.items())[:5]
        retained_audit = {name: self._classify_block(name) for name in retained_blocks}
        grouped_sizes = self._group_block_sizes(block_sizes)
        broker_guidance_present = self._broker_anchor_text(True)
        broker_guidance_absent = self._broker_anchor_text(False)
        current_broker_guidance = int(block_sizes.get("broker_guidance", 0))
        current_evidence_load = int(block_sizes.get("context_evidence", 0))
        estimated_if_evidence_absent = (
            len(prompt)
            - current_evidence_load
            - current_broker_guidance
            + len(broker_guidance_absent)
        )
        estimated_if_evidence_present = (
            len(prompt)
            - current_broker_guidance
            + len(broker_guidance_present)
        )
        evidence_mode = "broker_present" if evidence_items else "fallback_only"
        fallback_grounding_relied_upon = not bool(evidence_items)
        broker_load_chars = current_evidence_load + current_broker_guidance
        grounding_load_chars = grouped_sizes["live_context_chars"] + grouped_sizes["session_state_chars"] + int(block_sizes.get("actions", 0))
        evidence_coverage_ratio = round(
            broker_load_chars / max(1, broker_load_chars + grounding_load_chars),
            4,
        )
        retained_focus_sizes = {
            "structured_output_contract_chars": int(block_sizes.get("structured_output_contract", 0)),
            "discovery_anchor_chars": int(block_sizes.get("actions", 0)),
            "presentation_chars": int(block_sizes.get("presentation_directive", 0)),
            "response_persona_chars": int(block_sizes.get("response_persona", 0)),
            "specialist_chars": int(block_sizes.get("specialist_prompt", 0)),
            "instruction_pack_chars": int(block_sizes.get("instruction_pack", 0)),
            "toon_chars": int(block_sizes.get("toon_state", 0)) + int(block_sizes.get("toon_deltas", 0)),
            "session_state_chars": int(block_sizes.get("session_summary", 0)) + int(block_sizes.get("scratchpad", 0)) + int(block_sizes.get("cognitive_foreground", 0)) + int(block_sizes.get("cognitive_supporting", 0)),
            "broker_evidence_chars": int(block_sizes.get("context_evidence", 0)),
        }
        return {
            "estimated_before_pass5_chars": before_pass5_total,
            "estimated_after_pass5_chars": len(prompt),
            "estimated_before_pass4_chars": before_pass4_total,
            "estimated_after_pass4_chars": len(prompt),
            "estimated_before_pass2_chars": before_total,
            "estimated_after_pass2_chars": len(prompt),
            "estimated_before_chars": before_total,
            "estimated_after_chars": len(prompt),
            "estimated_reduction_chars": max(0, before_total - len(prompt)),
            "estimated_total_reduction_chars": max(0, before_total - len(prompt)),
            "estimated_pass4_reduction_chars": max(0, before_pass4_total - len(prompt)),
            "estimated_pass5_reduction_chars": max(0, before_pass5_total - len(prompt)),
            "broker_evidence_present": bool(evidence_items),
            "evidence_item_count": len(evidence_items),
            "evidence_domains": evidence_domains,
            "fallback_no_evidence_mode": not bool(evidence_items),
            "prompt_profile": prompt_profile,
            "discovery_mode": discovery_mode,
            "compact_discovery_used": discovery_mode in {"dense", "dense_hybrid", "chat", "od", "od_chat"},
            "retained_block_sizes": retained_blocks,
            "retained_focus_sizes": retained_focus_sizes,
            "dynamic_state_metrics": {
                "toon_chars": retained_focus_sizes["toon_chars"],
                "session_state_chars": retained_focus_sizes["session_state_chars"],
                **state_stats,
            },
            "evidence_density_metrics": {
                **evidence_stats,
                "evidence_chars": retained_focus_sizes["broker_evidence_chars"],
            },
            "largest_retained_blocks": largest_blocks,
            "largest_retained_blocks_audit": [
                {"block": name, "chars": size, "category": retained_audit.get(name, "D_grounding_compactable")}
                for name, size in largest_blocks
            ],
            "retained_block_audit": retained_audit,
            "grouped_load_chars": grouped_sizes,
            "evidence_mode_comparison": {
                "mode": evidence_mode,
                "domains": evidence_domains,
                "fallback_grounding_relied_upon": fallback_grounding_relied_upon,
                "broker_load_chars": broker_load_chars,
                "grounding_load_chars": grounding_load_chars,
                "estimated_prompt_chars_if_evidence_absent": max(0, estimated_if_evidence_absent),
                "estimated_prompt_chars_if_evidence_present": max(0, estimated_if_evidence_present),
                "evidence_coverage_ratio": evidence_coverage_ratio,
            },
            "replacement_modes": sorted(
                {
                    str(item.get("replacement") or "").strip()
                    for item in reduction_audit.values()
                    if str(item.get("replacement") or "").strip()
                }
            ),
            "reduction_audit": reduction_audit,
        }

    @staticmethod
    def _build_cognitive_projection_blocks(cognitive_projection: Dict[str, Any]) -> Tuple[str, str]:
        focus_lines = [
            str(item).strip()
            for item in list(cognitive_projection.get("focus_lines") or [])
            if str(item).strip()
        ]
        background_lines = [
            str(item).strip()
            for item in list(cognitive_projection.get("background_lines") or [])
            if str(item).strip()
        ]
        focus_block = "[FOCUS]\n" + "\n".join(focus_lines[:4]) if focus_lines else ""
        background_block = "[BACKGROUND]\n" + "\n".join(background_lines[:4]) if background_lines else ""
        return focus_block, background_block

    @staticmethod
    def _build_cognitive_blocks(cognitive_frame: Dict[str, Any]) -> Tuple[str, str]:
        focus_lines: List[str] = []
        objective = str(cognitive_frame.get("objective") or "").strip()
        if objective and objective != "Standby":
            focus_lines.append(f"objective={objective}")

        foreground = list(cognitive_frame.get("foreground_tasks") or [])
        if foreground:
            for task in foreground[:3]:
                task_id = str(task.get("task_id") or "?")
                role = str(task.get("role") or "task")
                status = str(task.get("status") or "unknown")
                summary = str(task.get("summary") or "").strip()
                focus_lines.append(f"active=[{task_id}] {role}|{status}" + (f"|{summary}" if summary else ""))
        else:
            focus_lines.append("active=none")

        blockers = [str(item).strip() for item in list(cognitive_frame.get("blockers") or []) if str(item).strip()]
        if blockers:
            focus_lines.append("blockers=" + " | ".join(blockers[:4]))

        background_lines: List[str] = []
        background_tasks = list(cognitive_frame.get("background_tasks") or [])
        for task in background_tasks[:4]:
            task_id = str(task.get("task_id") or "?")
            role = str(task.get("role") or "task")
            status = str(task.get("status") or "unknown")
            background_lines.append(f"background=[{task_id}] {role}|{status}")
        
        if not background_lines and not foreground:
            background_lines.append("tasks=idle")

        constraints = [str(item).strip() for item in list(cognitive_frame.get("constraints") or []) if str(item).strip()]
        if constraints:
            background_lines.append("constraints=" + " | ".join(constraints[:5]))

        focus_block = "[FOCUS]\n" + "\n".join(focus_lines) if focus_lines else ""
        background_block = "[BACKGROUND]\n" + "\n".join(background_lines) if background_lines else ""
        return focus_block, background_block

    @staticmethod
    def _classify_block(name: str) -> str:
        kernel = {
            "base_header",
            "execution_policy",
            "structured_output_contract",
        }
        live_context = {
            "system_context",
            "python_context",
            "browser_state",
            "attachments",
        }
        session_state = {
            "original_user_directive",
            "toon_state",
            "toon_deltas",
            "session_summary",
            "scratchpad",
            "relevant_memory",
            "cognitive_foreground",
            "cognitive_supporting",
        }
        if name in kernel:
            return "A_true_kernel"
        if name in live_context:
            return "B_live_context"
        if name in session_state:
            return "C_session_state"
        if name in {"instruction_pack", "actions", "broker_guidance", "context_evidence", "response_persona", "presentation_directive", "specialist_prompt"}:
            return "D_grounding_compactable"
        return "E_legacy_debt_or_misc"

    def _infer_prompt_profile(self, user_input: str) -> str:
        if self._has_any_keyword(user_input, self._TROUBLESHOOTING_KEYWORDS):
            return "troubleshooting"
        return "conversational" if self._is_conversational_turn(user_input) else "operational"

    @staticmethod
    def _extract_discovery_mode(capabilities_summary: str) -> str:
        first_line = str(capabilities_summary or "").splitlines()[0].strip()
        if first_line.startswith("m="):
            return first_line[2:].strip()
        return "unknown"

    @staticmethod
    def _is_conversational_turn(user_input: str) -> bool:
        text = str(user_input or "").strip().lower()
        if not text:
            return False
        greetings = {
            "oi",
            "ola",
            "olá",
            "hello",
            "hi",
            "hey",
            "bom dia",
            "boa tarde",
            "boa noite",
            "e ai",
            "e aí",
        }
        normalized = "".join(ch for ch in text if ch.isalnum() or ch.isspace()).strip()
        if normalized in greetings:
            return True
        if len(normalized) <= 12 and any(token in normalized for token in ("oi", "olá", "ola", "hello", "hi", "hey")):
            return True
        return False

    def _group_block_sizes(self, block_sizes: Dict[str, int]) -> Dict[str, int]:
        grouped = {
            "kernel_chars": 0,
            "live_context_chars": 0,
            "session_state_chars": 0,
            "grounding_chars": 0,
            "legacy_misc_chars": 0,
        }
        for name, size in block_sizes.items():
            category = self._classify_block(name)
            if category == "A_true_kernel":
                grouped["kernel_chars"] += int(size)
            elif category == "B_live_context":
                grouped["live_context_chars"] += int(size)
            elif category == "C_session_state":
                grouped["session_state_chars"] += int(size)
            elif category == "D_grounding_compactable":
                grouped["grounding_chars"] += int(size)
            else:
                grouped["legacy_misc_chars"] += int(size)
        return grouped

    def _prepare_context_evidence(
        self,
        context_bundle: ContextBundle | None,
        prompt_profile: str,
    ) -> Tuple[str, Dict[str, Any]]:
        evidence_items = list(getattr(context_bundle, "evidence_items", None) or [])
        if not evidence_items:
            return "", {
                "raw_count": 0,
                "kept_count": 0,
                "suppressed_count": 0,
                "kept_by_domain": {},
                "suppressed_by_domain": {},
                "best_of_domain_used": False,
            }

        if prompt_profile == "troubleshooting":
            max_total = 5
            per_domain_caps = {
                "agent_experience": 2,
                "procedures": 2,
                "capability_knowledge": 1,
                "policies": 1,
            }
        elif prompt_profile == "conversational":
            max_total = 3
            per_domain_caps = {}
        else:
            max_total = 4
            per_domain_caps = {
                "procedures": 1,
                "capability_knowledge": 1,
                "policies": 1,
                "examples": 1,
            }

        kept = []
        seen_fingerprints = set()
        kept_by_domain: Dict[str, int] = {}
        suppressed_by_domain: Dict[str, int] = {}
        for item in evidence_items:
            fingerprint = self._normalize_evidence_fingerprint(item.title, item.content)
            domain_cap = per_domain_caps.get(item.domain, 1)
            if fingerprint in seen_fingerprints:
                suppressed_by_domain[item.domain] = suppressed_by_domain.get(item.domain, 0) + 1
                continue
            if kept_by_domain.get(item.domain, 0) >= domain_cap:
                suppressed_by_domain[item.domain] = suppressed_by_domain.get(item.domain, 0) + 1
                continue
            kept.append(item)
            kept_by_domain[item.domain] = kept_by_domain.get(item.domain, 0) + 1
            seen_fingerprints.add(fingerprint)
            if len(kept) >= max_total:
                break

        if len(kept) < min(len(evidence_items), max_total):
            for item in evidence_items:
                if item in kept:
                    continue
                fingerprint = self._normalize_evidence_fingerprint(item.title, item.content)
                if fingerprint in seen_fingerprints:
                    suppressed_by_domain[item.domain] = suppressed_by_domain.get(item.domain, 0) + 1
                    continue
                kept.append(item)
                kept_by_domain[item.domain] = kept_by_domain.get(item.domain, 0) + 1
                seen_fingerprints.add(fingerprint)
                if len(kept) >= max_total:
                    break

        lines: List[str] = []
        for item in kept:
            lines.append(f"[EVIDENCE: {item.domain}]")
            lines.append(f"title: {item.title}")
            lines.append(f"content: {item.content}")
            lines.append(f"source: {item.source}")
            if item.score:
                lines.append(f"score: {item.score:.2f}")
            lines.append("")
        return "\n".join(lines).strip(), {
            "raw_count": len(evidence_items),
            "kept_count": len(kept),
            "suppressed_count": max(0, len(evidence_items) - len(kept)),
            "kept_by_domain": kept_by_domain,
            "suppressed_by_domain": suppressed_by_domain,
            "best_of_domain_used": True,
        }

    @staticmethod
    def _legacy_format_context_evidence(context_bundle: ContextBundle | None) -> str:
        if not context_bundle or not getattr(context_bundle, "evidence_items", None):
            return ""
        lines: List[str] = []
        for item in list(context_bundle.evidence_items)[:6]:
            lines.append(f"[EVIDENCE: {item.domain}]")
            lines.append(f"title: {item.title}")
            lines.append(f"content: {item.content}")
            lines.append(f"source: {item.source}")
            if item.score:
                lines.append(f"score: {item.score:.2f}")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _normalize_evidence_fingerprint(title: str, content: str) -> str:
        combined = f"{title} {content}".lower()
        return " ".join("".join(ch if ch.isalnum() or ch.isspace() else " " for ch in combined).split())

    def _clip_state_block(
        self,
        block_name: str,
        text: str,
        prompt_profile: str,
        has_evidence: bool,
        has_summary: bool,
    ) -> str:
        limit = int(self.block_budgets.get(block_name, 2000))
        if prompt_profile == "conversational":
            limit = int(limit * 0.65)
        elif prompt_profile == "troubleshooting":
            limit = int(limit * 0.85)
        if has_evidence and block_name in {"toon_state", "session_summary", "scratchpad", "relevant_memory"}:
            limit = int(limit * 0.8)
        if has_summary and block_name in {"toon_state", "scratchpad"}:
            limit = int(limit * 0.85)
        return self._clip_block_custom(block_name, text, max(240, limit))

    def _clip_block_custom(self, block_name: str, text: str, limit: int) -> str:
        value = (text or "").strip()
        if len(value) <= limit:
            return value
        clipped = value[:limit].rstrip()
        return f"{clipped}\n...[truncated:{block_name}]"

    @staticmethod
    def _state_text_is_redundant(primary: str, secondary: str) -> bool:
        primary_norm = " ".join(str(primary or "").lower().split())
        secondary_norm = " ".join(str(secondary or "").lower().split())
        if not primary_norm or not secondary_norm:
            return False
        if secondary_norm in primary_norm or primary_norm in secondary_norm:
            return True
        primary_tokens = set(primary_norm.split())
        secondary_tokens = set(secondary_norm.split())
        overlap = len(primary_tokens & secondary_tokens)
        return overlap >= max(4, min(len(primary_tokens), len(secondary_tokens)) * 0.7)
