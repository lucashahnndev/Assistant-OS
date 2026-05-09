import datetime
import logging
import os
import platform
import re
from typing import Any, Dict, List

from ..base import CapabilityBase
from utils.toon_codec import encode_capabilities_list, encode_capabilities_describe

try:
    import pyautogui
except BaseException:
    pyautogui = None


logger = logging.getLogger("SystemCapability")


class SystemCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "system"

    @property
    def name(self) -> str:
        return "system"

    @property
    def actions(self) -> List[str]:
        return [
            "status",
            "cancel",
            "consult_tools",
            "capabilities.list",
            "capabilities.list.ai",
            "capabilities.list.ui",
            "capabilities.describe",
            "capabilities.describe.ai",
            "capabilities.describe.ui",
            "screenshot",
            "info",
            "time",
            "power",
            "process.list",
            "process.kill",
            "network.status",
            "network.ping",
            "service.manage",
            "service.logs",
            "fs.list",
            "fs.read",
            "fs.write",
            "fs.delete",
            "keyboard",
        ]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "pattern": r"^/status(?:\s+(\S+))?",
                "action_id": "system.control.status",
                "handler": lambda m: {"work_id": m.group(1)},
            },
            {
                "pattern": r"^/cancel(?:\s+(\S+))?",
                "action_id": "system.control.cancel",
                "handler": lambda m: {"work_id": m.group(1)},
            },
        ]

    @staticmethod
    def _result(ok: bool, status: str, message: str = "", error_code: str = "", **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status}
        if message:
            payload["message"] = message
        if error_code:
            payload["error_code"] = error_code
        payload.update(extra)
        return payload

    @staticmethod
    def _is_error_text(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        v = value.strip().lower()
        return v.startswith("error") or v.startswith("access denied") or v.startswith("invalid action")

    @staticmethod
    def _to_int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
        try:
            out = int(value)
        except Exception:
            out = default
        if min_value is not None:
            out = max(min_value, out)
        if max_value is not None:
            out = min(max_value, out)
        return out

    def _local_action(self, action_id: str) -> str:
        if "." not in action_id:
            return action_id
        return action_id.split(".", 2)[-1]

    def _system_driver(self, context: Dict[str, Any]) -> Any:
        return context.get("system_driver") or (getattr(self.kernel, "system_driver", None) if self.kernel else None)

    def _keyboard_action(self, params: Dict[str, Any]) -> str:
        explicit = str(params.get("action") or "").strip().lower()
        if explicit:
            return explicit

        cmd = str(params.get("command") or "").lower()
        if "proximo" in cmd or "next" in cmd:
            return "next"
        if "anterior" in cmd or "prev" in cmd:
            return "prev"
        if "pausa" in cmd or "pause" in cmd or "play" in cmd:
            return "pause"
        if "aumentar volume" in cmd or "vol_up" in cmd or "volume_up" in cmd:
            return "volume_up"
        if "diminuir volume" in cmd or "vol_down" in cmd or "volume_down" in cmd:
            return "volume_down"
        if "mudo" in cmd or "mute" in cmd:
            return "mute"
        if "fechar" in cmd or "close" in cmd:
            return "close"
        return ""

    @staticmethod
    def _looks_like_capability_query(query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return False
        markers = (
            "capability",
            "capabilities",
            "ação",
            "acoes",
            "ações",
            "action",
            "actions",
            "namespace",
            "catalog",
            "catálogo",
            "contract",
            "contrato",
        )
        if any(m in q for m in markers):
            return True
        # Typical action-id pattern.
        if "." in q and len(q.split(".")) >= 2:
            return True
        return False

    @staticmethod
    def _looks_like_explicit_browser_request(query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return False
        markers = (
            "abrir site",
            "abra o site",
            "abre o site",
            "abrir navegador",
            "abra o navegador",
            "abre o navegador",
            "navegar",
            "navegação",
            "navigation",
            "clicar",
            "clique",
            "preencher",
            "formulário",
            "formulario",
            "interagir com a página",
            "interagir com pagina",
            "interagir com página",
            "browser",
            "site",
            "web",
            "tela",
            "na tela",
            "visualmente",
        )
        return any(marker in q for marker in markers)

    @staticmethod
    def _browser_action_preference(query: str) -> str:
        q = str(query or "").strip().lower()
        if not q:
            return ""
        close_markers = (
            "fechar aba",
            "feche a aba",
            "fechar navegador",
            "feche o navegador",
            "encerrar navegador",
            "close tab",
            "close browser",
            "quit browser",
            "sair do navegador",
        )
        run_markers = (
            "abrir site",
            "abra o site",
            "abre o site",
            "abrir navegador",
            "abra o navegador",
            "abre o navegador",
            "navegar",
            "navegação",
            "navigation",
            "clicar",
            "clique",
            "preencher",
            "formulário",
            "formulario",
            "interagir com a página",
            "interagir com pagina",
            "interagir com página",
            "browser",
            "site",
            "web",
            "tela",
            "na tela",
            "visualmente",
            "pesquisar",
            "pesquise",
            "buscar",
        )
        if any(marker in q for marker in close_markers):
            return "close"
        if any(marker in q for marker in run_markers):
            return "run"
        return ""

    @staticmethod
    def _tokenize_query(text: str) -> List[str]:
        return [token for token in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(token) > 2]

    @classmethod
    def _semantic_query_boost(cls, query: str, *texts: str) -> float:
        query_tokens = set(cls._tokenize_query(query))
        if not query_tokens:
            return 0.0
        text_tokens: set[str] = set()
        joined_parts: List[str] = []
        for text in texts:
            if not text:
                continue
            joined_parts.append(str(text))
            text_tokens.update(cls._tokenize_query(str(text)))
        if not text_tokens:
            return 0.0
        overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
        joined = " ".join(joined_parts).lower()
        exact = 0.0
        if any(token in joined for token in query_tokens):
            exact = 0.08
        if str(query or "").strip().lower() and str(query).strip().lower() in joined:
            exact = max(exact, 0.12)
        return min(0.25, round((overlap * 0.18) + exact, 4))

    @staticmethod
    def _query_family(query: str) -> str:
        q = str(query or "").strip().lower()
        if not q:
            return ""
        if any(marker in q for marker in ("calendar", "calendario", "calendário", "agenda", "schedule", "appointment", "eventos", "compromisso", "compromissos")):
            return "calendar"
        if any(marker in q for marker in ("weather", "forecast", "clima", "tempo", "chuva", "temperatura")):
            return "weather"
        if any(marker in q for marker in ("remember", "recall", "memory", "memoria", "memória", "lembra", "preferencia", "preferência")):
            return "memory"
        if any(marker in q for marker in ("browser", "navegador", "site", "web", "tela", "clicar", "navegar", "abrir site", "abra o navegador", "abra o site")):
            return "browser"
        return ""

    @staticmethod
    def _family_affinity_boost(query_family: str, action_id: str, metadata: Dict[str, Any], query: str, explicit_browser: bool) -> float:
        family = str(query_family or "").strip().lower()
        if not family:
            return 0.0
        action_l = str(action_id or "").strip().lower()
        namespace = str(metadata.get("namespace") or "").strip().lower()
        capability_id = str(metadata.get("capability_id") or "").strip().lower()
        title = str(metadata.get("title") or "").strip().lower()
        description = str(metadata.get("description") or "").strip().lower()
        haystack = " ".join([action_l, namespace, capability_id, title, description])
        score = 0.0
        if family == "calendar":
            if "google" in str(query or "").lower() and ("google" in haystack or "sync" in haystack):
                score += 0.12
            elif any(token in haystack for token in ("calendar", "agenda", "appointment", "event")):
                score += 0.24
            if action_l.startswith("browser.control.") or namespace.startswith(("research.retrieve", "web.", "ddg.", "brave.", "searxng.", "commoncrawl.", "wikipedia")):
                score -= 0.35
            if capability_id == "google_calendar" and not any(token in str(query or "").lower() for token in ("google", "sync", "sincron", "sincronizar")):
                score -= 0.18
        elif family == "weather":
            if any(token in haystack for token in ("weather", "clima", "tempo", "forecast")):
                score += 0.22
            if action_l.startswith("browser.control.") or namespace.startswith(("research.retrieve", "web.", "ddg.", "brave.", "searxng.", "commoncrawl.", "wikipedia")):
                score -= 0.15
        elif family == "memory":
            if any(token in haystack for token in ("memory", "memoria", "memória", "remember", "recall", "preference")):
                score += 0.20
        elif family == "browser":
            if action_l == "browser.control.run":
                score += 0.30 if explicit_browser else 0.08
            elif action_l.startswith("browser.control.close"):
                score += 0.18 if any(marker in str(query or "").lower() for marker in ("fechar", "close", "encerrar", "sair")) else -0.04
            elif action_l.startswith("browser.control."):
                score += 0.12 if explicit_browser else -0.06
        return max(-0.4, min(0.35, round(score, 4)))

    @staticmethod
    def _actions_for_capability(registry, capability_id: str) -> List[str]:
        cap_id = str(capability_id or "").strip()
        if not cap_id or registry is None:
            return []
        contract = getattr(registry, "capability_contracts", {}).get(cap_id) if hasattr(registry, "capability_contracts") else None
        if contract and getattr(contract, "actions", None):
            actions = [str(action.id).strip() for action in contract.actions if str(getattr(action, "id", "")).strip()]
            if actions:
                return actions
        if not hasattr(registry, "list_actions") or not hasattr(registry, "get_action_metadata"):
            return []
        actions: List[str] = []
        for action_id in registry.list_actions():
            meta = registry.get_action_metadata(action_id) or {}
            if str(meta.get("capability_id") or "").strip() == cap_id:
                actions.append(action_id)
        return actions

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        local = self._local_action(action_id)

        if local == "consult_tools":
            orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
            registry = getattr(orch, "capability_registry", None)
            broker = getattr(orch, "context_broker", None) if orch else None
            if not registry:
                return self._result(
                    ok=False,
                    status="error",
                    message="Capability registry not available.",
                    error_code="SKILL_REGISTRY_UNAVAILABLE",
                )

            # Fall back to the current user input when the model omits the
            # query field. This keeps discovery generic and avoids collapsing
            # into the fallback catalog when the planner under-specifies args.
            query = str(params.get("query") or context.get("user_input") or "").strip()
            intent = str(params.get("intent") or "").strip().lower()
            domain = str(params.get("domain") or "").strip().lower()
            role = str(params.get("role") or "").strip().lower()
            entity_type = str(params.get("entity_type") or "").strip().lower()
            limit = self._to_int(params.get("limit"), default=5, min_value=1, max_value=12)
            include_descriptions = bool(params.get("include_descriptions", True))
            output_format = str(params.get("format") or "toon").strip().lower()

            config_mgr = getattr(orch, "config_manager", None)
            sys_ctrl_cfg = config_mgr.get("capabilities", {}).get("system_control", {}) if config_mgr else {}
            librarian_cfg = sys_ctrl_cfg.get("librarian", {}) if isinstance(sys_ctrl_cfg, dict) else {}
            lib_mode = str(librarian_cfg.get("mode", "agentic")).strip().lower() if librarian_cfg.get("enabled") else "math_only"
            dynamic_threshold = float(librarian_cfg.get("dynamic_threshold", 0.70))
            max_tools = int(librarian_cfg.get("max_tools_to_evaluate", 5))
            broker_intent = ""
            broker_domains: List[str] = []
            broker_evidence_items: List[Any] = []

            if broker and hasattr(broker, "build_bundle"):
                try:
                    broker_session = context.get("session")
                    broker_bundle = broker.build_bundle(
                        user_input=query or "tool discovery",
                        session=broker_session,
                        capability_registry=registry,
                        allowed_actions=context.get("allowed_actions") if isinstance(context.get("allowed_actions"), list) else None,
                        broker_hints={"signal_strength": "medium", "source": "consult_tools"},
                    )
                    broker_intent = str(getattr(getattr(broker_bundle, "diagnostics", None), "intent", "") or "").strip().lower()
                    broker_domains = [
                        str(x).strip().lower()
                        for x in list(getattr(getattr(broker_bundle, "diagnostics", None), "evidence_domains", []) or [])
                        if str(x).strip()
                    ][:6]
                    broker_evidence_items = list(getattr(broker_bundle, "evidence_items", []) or [])
                except Exception as exc:
                    logger.debug("Consult tools broker enrichment unavailable: %s", exc)

            focus_rows: List[Dict[str, Any]] = []
            if query and hasattr(registry, "get_focus_actions"):
                try:
                    focus_rows = registry.get_focus_actions(
                        user_input=query,
                        allowed_actions=context.get("allowed_actions") if isinstance(context.get("allowed_actions"), list) else None,
                        limit=max(limit, 8),
                    )
                except Exception as exc:
                    logger.warning("Consult tools failed to rank focus actions: %s", exc)
                    focus_rows = []

            allowed_set = set(context.get("allowed_actions")) if isinstance(context.get("allowed_actions"), list) else None
            explicit_browser = self._looks_like_explicit_browser_request(query)
            query_family = self._query_family(query)
            ranked_by_action: Dict[str, Dict[str, Any]] = {}
            capability_evidence = [
                item
                for item in (broker_evidence_items if isinstance(broker_evidence_items, list) else [])
                if str(getattr(item, "domain", "") or "").strip().lower() == "capability_knowledge"
            ]

            def _upsert_row(
                *,
                action_id: str,
                score: float,
                reason: str,
                source: str,
                metadata: Dict[str, Any] | None = None,
                setup_ready: bool | None = None,
                roles: List[str] | None = None,
                domains: List[str] | None = None,
                entity_types: List[str] | None = None,
                capability_id: str = "",
            ) -> None:
                if not action_id:
                    return
                if allowed_set is not None and action_id not in allowed_set:
                    return
                existing = ranked_by_action.get(action_id)
                if existing and float(existing.get("score") or 0.0) >= float(score or 0.0):
                    return
                meta = metadata if isinstance(metadata, dict) else {}
                row = {
                    "action_id": action_id,
                    "capability_id": str(meta.get("capability_id") or capability_id or ""),
                    "namespace": str(meta.get("namespace") or ""),
                    "title": str(meta.get("title") or action_id.split(".")[-1].replace("_", " ").title()),
                    "description": str(meta.get("description") or ""),
                    "risk_level": str(meta.get("risk_level") or "low"),
                    "score": round(float(score), 3),
                    "reason": reason,
                    "source": source,
                }
                if include_descriptions:
                    row["setup_ready"] = setup_ready
                    row["roles"] = list(roles or [])
                    row["domains"] = list(domains or [])
                    row["entity_types"] = list(entity_types or [])
                ranked_by_action[action_id] = row

            for item in capability_evidence:
                metadata = item.metadata if isinstance(getattr(item, "metadata", None), dict) else {}
                capability_id = str(metadata.get("capability_id") or "").strip()
                action_id = str(metadata.get("action_id") or "").strip()
                doc_type = str(metadata.get("doc_type") or "").strip()
                item_title = str(getattr(item, "title", "") or "")
                item_content = str(getattr(item, "content", "") or "")
                item_score = float(getattr(item, "score", 0.0) or 0.0)
                if action_id:
                    resolved = action_id
                    metadata = registry.get_action_metadata(resolved) if hasattr(registry, "get_action_metadata") else metadata
                    score = item_score + self._semantic_query_boost(query, resolved, metadata.get("title"), metadata.get("description"), item_title, item_content)
                    score += self._family_affinity_boost(query_family, resolved, metadata, query, explicit_browser)
                    _upsert_row(
                        action_id=resolved,
                        score=max(0.0, min(1.0, score)),
                        reason=f"capability_knowledge:{doc_type or 'doc'}",
                        source="capability_knowledge_rag",
                        metadata=metadata,
                        capability_id=capability_id,
                    )
                    continue

                if not capability_id:
                    continue
                candidate_actions = self._actions_for_capability(registry, capability_id)
                for idx, candidate_action in enumerate(candidate_actions[:3]):
                    resolved = candidate_action
                    metadata = registry.get_action_metadata(resolved) if hasattr(registry, "get_action_metadata") else {}
                    score = item_score - (idx * 0.03) + self._semantic_query_boost(query, resolved, metadata.get("title"), metadata.get("description"), item_title, item_content)
                    score += self._family_affinity_boost(query_family, resolved, metadata, query, explicit_browser)
                    _upsert_row(
                        action_id=resolved,
                        score=max(0.0, min(1.0, score)),
                        reason=f"capability_knowledge:{doc_type or 'capability'}",
                        source="capability_knowledge_rag",
                        metadata=metadata,
                        capability_id=capability_id,
                    )

            if len(ranked_by_action) < limit:
                offers: List[Dict[str, Any]] = []
                if hasattr(registry, "list_discovery_offers"):
                    try:
                        offers = registry.list_discovery_offers(
                            intent=intent or broker_intent or None,
                            domain=domain or None,
                            role=role or None,
                            entity_type=entity_type or None,
                        )
                    except Exception as exc:
                        logger.warning("Consult tools failed to list discovery offers: %s", exc)
                        offers = []
                elif hasattr(registry, "list_retrieval_offers"):
                    try:
                        offers = registry.list_retrieval_offers(
                            intent=intent or broker_intent or None,
                            domain=domain or None,
                            role=role or None,
                            entity_type=entity_type or None,
                        )
                    except Exception as exc:
                        logger.warning("Consult tools failed to list retrieval offers: %s", exc)
                        offers = []

                for offer in offers:
                    capability_id = str(offer.get("capability_id") or "").strip()
                    action_ids = [str(x).strip() for x in (offer.get("actions") or []) if str(x or "").strip()]
                    if not action_ids:
                        continue
                    setup_ready = bool(offer.get("setup_ready"))
                    domains = [str(x).strip() for x in (offer.get("domains") or []) if str(x or "").strip()]
                    roles = [str(x).strip() for x in (offer.get("roles") or []) if str(x or "").strip()]
                    entity_types = [str(x).strip() for x in (offer.get("entity_types") or []) if str(x or "").strip()]
                    base_score = 0.52
                    if domain and domain in domains:
                        base_score += 0.08
                    if broker_domains and any(broker_domain in domains for broker_domain in broker_domains):
                        base_score += 0.05
                    if role and role in roles:
                        base_score += 0.05
                    if entity_type and entity_type in entity_types:
                        base_score += 0.05
                    if setup_ready:
                        base_score += 0.05
                    keywords = [str(x).strip().lower() for x in (offer.get("keywords") or []) if str(x).strip()]
                    if query and keywords:
                        query_l = query.lower()
                        keyword_hits = sum(1 for kw in keywords if kw in query_l)
                        if keyword_hits:
                            base_score += min(0.12, 0.04 * keyword_hits)
                    browser_namespace = str(offer.get("namespace") or "").strip().lower().startswith("browser.control")
                    reason_suffix = ""
                    if query:
                        if browser_namespace and not explicit_browser:
                            base_score -= 0.28
                            reason_suffix = "browser_not_explicit"
                        elif browser_namespace and explicit_browser:
                            base_score += 0.30
                            reason_suffix = "explicit_browser_request"
                    reason = f"discoverability_offer:{capability_id or 'unknown'}"
                    for idx, action_id in enumerate(action_ids[:3]):
                        score = base_score - (idx * 0.03)
                        if query and explicit_browser and browser_namespace:
                            browser_preference = self._browser_action_preference(query)
                            if browser_preference == "run" and action_id == "browser.control.run":
                                score += 0.08
                            elif browser_preference == "run" and action_id.startswith("browser.control.close"):
                                score -= 0.10
                            elif browser_preference == "close" and action_id.startswith("browser.control.close"):
                                score += 0.08
                            elif browser_preference == "close" and action_id == "browser.control.run":
                                score -= 0.10
                        metadata = registry.get_action_metadata(action_id) if hasattr(registry, "get_action_metadata") else {}
                        score += self._semantic_query_boost(query, action_id, metadata.get("title"), metadata.get("description"))
                        score += self._family_affinity_boost(query_family, action_id, metadata, query, explicit_browser)
                        _upsert_row(
                            action_id=action_id,
                            score=max(0.0, min(1.0, score)),
                            reason=f"{reason}:{reason_suffix}" if query and reason_suffix else reason,
                            source="discoverability_offer",
                            metadata=metadata,
                            setup_ready=setup_ready,
                            roles=roles,
                            domains=domains,
                            entity_types=entity_types,
                            capability_id=capability_id,
                        )

                for row in focus_rows:
                    action_id = str(row.get("id") or "").strip()
                    if not action_id:
                        continue
                    score = float(row.get("score") or 0.0)
                    metadata = registry.get_action_metadata(action_id) if hasattr(registry, "get_action_metadata") else {}
                    if query and action_id.startswith("browser.control.") and not explicit_browser:
                        score = max(0.0, score - 0.30)
                        row["browser_penalty"] = True
                    score += self._semantic_query_boost(query, action_id, metadata.get("title"), metadata.get("description"), row.get("description"))
                    score += self._family_affinity_boost(query_family, action_id, metadata, query, explicit_browser)
                    _upsert_row(
                        action_id=action_id,
                        score=score,
                        reason="semantic_focus",
                        source="focus_ranker",
                        metadata=metadata,
                    )

                if not ranked_by_action and hasattr(registry, "list_actions"):
                    for action_id in registry.list_actions():
                        metadata = registry.get_action_metadata(action_id) if hasattr(registry, "get_action_metadata") else {}
                        _upsert_row(
                            action_id=action_id,
                            score=0.0,
                            reason="fallback_catalog",
                            source="registry",
                            metadata=metadata,
                        )

            ranked = sorted(ranked_by_action.values(), key=lambda item: (-float(item.get("score") or 0.0), str(item.get("action_id") or "")))
            
            filtered_ranked = [item for item in ranked if float(item.get("score") or 0.0) >= dynamic_threshold]
            if not filtered_ranked and ranked:
                filtered_ranked = [ranked[0]]
            ranked = filtered_ranked[:max_tools]
            primary = ranked[0] if ranked else {}

            advisory_report = None
            if lib_mode == "agentic" and ranked and orch and hasattr(orch, "llm_manager"):
                try:
                    tools_summary = "\n".join([f"- {i['action_id']} (Score: {i['score']}): {i.get('description', '')}" for i in ranked])
                    prompt = (
                        f"The user wants: '{query}'\n"
                        f"I have pre-filtered the best tools:\n{tools_summary}\n\n"
                        f"Write a brief 'Advisory Bula' for the CEO Agent explaining which tool to use, why, and any latency/risk warnings. Be concise."
                    )
                    system_prompt = "You are the internal routing Librarian. Your output is read by the Main Agent, not the user. Provide concise, strategic tool advice."
                    advisory_report = orch.llm_manager.generate_text(prompt=prompt, system_prompt=system_prompt)
                except Exception as e:
                    logger.warning(f"Librarian agentic pass failed: {e}")

            payload = {
                "query": query,
                "intent": intent or broker_intent or None,
                "domain": domain or None,
                "role": role or None,
                "entity_type": entity_type or None,
                "broker_domains": broker_domains[:6] or None,
                "discovery_source": "capability_knowledge_rag" if capability_evidence else "discoverability_offers",
                "count": len(ranked),
                "primary_action_id": str(primary.get("action_id") or "").strip() or None,
                "primary_score": primary.get("score") if primary else None,
                "primary_reason": str(primary.get("reason") or "").strip() or None,
                "advisory_report": advisory_report,
                "items": ranked,
            }

            if output_format == "legacy":
                return self._result(
                    ok=True,
                    status="success" if ranked else "empty",
                    **payload,
                )

            toon_items = []
            for item in ranked:
                toon_items.append(
                    {
                        "a": item.get("action_id"),
                        "c": item.get("capability_id"),
                        "n": item.get("namespace"),
                        "t": item.get("title"),
                        "d": item.get("description") if include_descriptions else "",
                        "r": item.get("risk_level"),
                        "s": item.get("score"),
                        "why": item.get("reason"),
                        "src": item.get("source"),
                    }
                )
            return self._result(
                ok=True,
                status="success" if ranked else "empty",
                query=query,
                intent=intent or broker_intent or None,
                domain=domain or None,
                role=role or None,
                entity_type=entity_type or None,
                broker_domains=broker_domains[:6] or None,
                discovery_source="capability_knowledge_rag" if capability_evidence else "discoverability_offers",
                count=len(ranked),
                primary_action_id=str(primary.get("action_id") or "").strip() or None,
                primary_score=primary.get("score") if primary else None,
                primary_reason=str(primary.get("reason") or "").strip() or None,
                advisory_report=advisory_report,
                toon={
                    "v": "toon.v1",
                    "t": "tools.consult",
                    "n": len(toon_items),
                    "i": toon_items,
                    "p": str(primary.get("action_id") or "").strip() or None,
                    "adv": advisory_report,
                },
            )

        if local == "info":
            from config.manager import ConfigManager
            from zoneinfo import ZoneInfo
            tz_name = ConfigManager().get_timezone()
            try:
                now = datetime.datetime.now(ZoneInfo(tz_name))
            except Exception:
                now = datetime.datetime.now(datetime.timezone.utc)
            payload = {
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "timezone": tz_name,
                "os": platform.system(),
                "dist": platform.release(),
                "user": os.getlogin() if hasattr(os, "getlogin") else "unknown",
            }
            return self._result(
                ok=True,
                status="success",
                message=f"System info: {payload['os']} {payload['dist']} ({payload['date']} {payload['time']}).",
                info=payload,
            )

        if local == "time":
            from config.manager import ConfigManager
            from zoneinfo import ZoneInfo
            tz_name = ConfigManager().get_timezone()
            try:
                now_dt = datetime.datetime.now(ZoneInfo(tz_name))
            except Exception:
                now_dt = datetime.datetime.now(datetime.timezone.utc)
            now = now_dt.strftime("%H:%M:%S")
            today = now_dt.strftime("%Y-%m-%d")
            include_date = bool(params.get("include_date"))
            if include_date:
                return self._result(
                    ok=True,
                    status="success",
                    message=f"Current date is {today} and time is {now}.",
                    date=today,
                    time=now,
                )
            return self._result(ok=True, status="success", message=f"Current time is {now}.", date=today, time=now)

        if local in {"capabilities.list", "capabilities.list.ai", "capabilities.list.ui"}:
            orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
            registry = getattr(orch, "capability_registry", None)
            if not registry:
                return self._result(
                    ok=False,
                    status="error",
                    message="Capability registry not available.",
                    error_code="SKILL_REGISTRY_UNAVAILABLE",
                )

            allowed_actions = context.get("allowed_actions")
            mode = "ai"
            if local.endswith(".ui"):
                mode = "ui"
            elif local.endswith(".ai"):
                mode = "ai"
            output_format = str(params.get("format") or ("legacy" if mode == "ui" else "toon")).strip().lower()
            include_descriptions = bool(params.get("include_descriptions", mode == "ui"))
            limit = self._to_int(params.get("limit"), default=40, min_value=1, max_value=200)
            query = str(params.get("query") or "").strip().lower()
            query_ignored = False
            if mode == "ai" and query and not self._looks_like_capability_query(query):
                # Protect on-demand flow: non-capability queries (e.g. song/web text) should not empty the catalog.
                query = ""
                query_ignored = True

            rows = registry.get_catalog(
                allowed_actions=allowed_actions if isinstance(allowed_actions, list) else None,
                include_descriptions=include_descriptions,
            )
            if query:
                rows = [
                    r
                    for r in rows
                    if query in str(r.get("id", "")).lower()
                    or query in str(r.get("namespace", "")).lower()
                    or query in str(r.get("description", "")).lower()
                ]
            rows = rows[:limit]
            if output_format == "legacy":
                return self._result(
                    ok=True,
                    status="success" if rows else "empty",
                    message=f"Capability catalog returned {len(rows)} action(s).",
                    count=len(rows),
                    items=rows,
                    catalog_mode="on_demand",
                    format="legacy",
                    audience=mode,
                )

            toon = encode_capabilities_list(rows, include_description=include_descriptions)
            return self._result(
                ok=True,
                status="success" if rows else "empty",
                message=f"Capability catalog returned {len(rows)} action(s) in TOON format.",
                count=len(rows),
                toon=toon,
                catalog_mode="on_demand",
                format="toon",
                audience=mode,
                query_ignored=query_ignored,
            )

        if local in {"capabilities.describe", "capabilities.describe.ai", "capabilities.describe.ui"}:
            orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
            registry = getattr(orch, "capability_registry", None)
            if not registry:
                return self._result(
                    ok=False,
                    status="error",
                    message="Capability registry not available.",
                    error_code="SKILL_REGISTRY_UNAVAILABLE",
                )

            requested: List[str] = []
            one = str(params.get("action_id") or "").strip()
            many = params.get("action_ids")
            if one:
                requested.append(one)
            if isinstance(many, list):
                for item in many:
                    v = str(item or "").strip()
                    if v:
                        requested.append(v)

            if not requested:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'action_id' or 'action_ids'.",
                    error_code="MISSING_ACTION_ID",
                )

            allowed_actions = context.get("allowed_actions")
            mode = "ai"
            if local.endswith(".ui"):
                mode = "ui"
            elif local.endswith(".ai"):
                mode = "ai"
            output_format = str(params.get("format") or ("legacy" if mode == "ui" else "toon")).strip().lower()
            allowed_set = set(allowed_actions) if isinstance(allowed_actions, list) else None

            details: List[Dict[str, Any]] = []
            for action_id in requested[:50]:
                resolved = action_id
                if allowed_set is not None and resolved not in allowed_set:
                    details.append(
                        {
                            "id": action_id,
                            "ok": False,
                            "error_code": "ACTION_NOT_ALLOWED",
                        }
                    )
                    continue
                metadata = registry.get_action_metadata(resolved)
                details.append(
                    {
                        "id": resolved,
                        "ok": bool(metadata),
                        "metadata": metadata or {},
                    }
                )

            if output_format == "legacy":
                return self._result(
                    ok=True,
                    status="success",
                    message=f"Returned details for {len(details)} action(s).",
                    count=len(details),
                    items=details,
                    format="legacy",
                    audience=mode,
                )

            toon = encode_capabilities_describe(details)
            return self._result(
                ok=True,
                status="success",
                message=f"Returned details for {len(details)} action(s) in TOON format.",
                count=len(details),
                toon=toon,
                format="toon",
                audience=mode,
            )

        sd = self._system_driver(context)
        if not sd:
            return self._result(
                ok=False,
                status="error",
                error_code="SYSTEM_DRIVER_UNAVAILABLE",
                message="System driver is required for this action.",
            )

        if local == "status":
            work_id = params.get("work_id")
            scheduler = getattr(self.kernel, "scheduler", None) if self.kernel else None
            if work_id:
                if not scheduler:
                    return self._result(
                        ok=False,
                        status="error",
                        message="System status unavailable (local execution).",
                        error_code="STATUS_UNAVAILABLE",
                    )
                work = scheduler.get_work(work_id)
                if not work:
                    return self._result(
                        ok=True,
                        status="empty",
                        message=f"Work '{work_id}' not found.",
                        work_id=work_id,
                        work=None,
                    )
                data = work.to_dict() if hasattr(work, "to_dict") else work
                return self._result(
                    ok=True,
                    status="success",
                    message=f"Status loaded for work '{work_id}'.",
                    work_id=work_id,
                    work=data,
                )

            if not scheduler:
                return self._result(
                    ok=False,
                    status="error",
                    message="System status unavailable (local execution).",
                    error_code="STATUS_UNAVAILABLE",
                )

            active = scheduler.list_active_works() if scheduler else []
            return self._result(
                ok=True,
                status="success" if active else "empty",
                message=f"Active works: {len(active)}.",
                count=len(active),
                works=active,
            )

        if local == "cancel":
            work_id = str(params.get("work_id") or "").strip()
            scheduler = getattr(self.kernel, "scheduler", None) if self.kernel else None
            if not work_id:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'work_id'.",
                    error_code="MISSING_WORK_ID",
                )
            if not scheduler:
                return self._result(
                    ok=False,
                    status="error",
                    message="Kernel scheduler not available.",
                    error_code="SCHEDULER_UNAVAILABLE",
                )
            scheduler.request_cancel(work_id)
            return self._result(
                ok=True,
                status="success",
                message=f"Cancellation requested for work '{work_id}'.",
                work_id=work_id,
            )

        if local == "screenshot":
            sid = context.get("session_id")
            filename = str(params.get("output_file") or params.get("filename") or "screenshot.png")
            screenshot_path = sd.take_screenshot(filename, session_id=sid)
            if self._is_error_text(screenshot_path):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Screenshot failed: {screenshot_path}",
                    error_code="SCREENSHOT_FAILED",
                )
            return self._result(
                ok=True,
                status="success",
                message=f"Screenshot saved to {screenshot_path}.",
                path=screenshot_path,
                session_id=sid,
            )

        if local == "power":
            command = str(params.get("action") or params.get("command") or "").lower()
            if "reboot" in command or "restart" in command:
                out = sd.power_reboot()
                return self._result(
                    ok=not self._is_error_text(out),
                    status="success" if not self._is_error_text(out) else "error",
                    message=str(out),
                    action="reboot",
                    output=out,
                )
            if "shutdown" in command or "off" in command:
                out = sd.power_shutdown()
                return self._result(
                    ok=not self._is_error_text(out),
                    status="success" if not self._is_error_text(out) else "error",
                    message=str(out),
                    action="shutdown",
                    output=out,
                )
            return self._result(
                ok=False,
                status="error",
                message=f"Unknown power command: '{command}'. Use 'reboot' or 'shutdown'.",
                error_code="UNKNOWN_POWER_COMMAND",
            )

        if local == "process.list":
            name_contains = params.get("name_contains")
            user = params.get("user")
            sort = str(params.get("sort") or "cpu")
            items = sd.list_processes(name_contains, user, sort)
            if not isinstance(items, list):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Unable to list processes: {items}",
                    error_code="PROCESS_LIST_FAILED",
                )
            return self._result(
                ok=True,
                status="success" if items else "empty",
                message=f"Processes listed: {len(items)}.",
                count=len(items),
                results=items,
            )

        if local == "process.kill":
            pid = params.get("pid")
            if pid is None:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'pid'.",
                    error_code="MISSING_PID",
                )
            signal = str(params.get("signal") or "TERM")
            out = sd.kill_process(int(pid), signal)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out),
                pid=int(pid),
                signal=signal,
                output=out,
            )

        if local == "network.status":
            out = sd.net_status()
            if isinstance(out, str) and self._is_error_text(out):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Network status failed: {out}",
                    error_code="NETWORK_STATUS_FAILED",
                )
            return self._result(
                ok=True,
                status="success",
                message="Network status retrieved.",
                result=out,
            )

        if local == "network.ping":
            host = str(params.get("host") or "").strip()
            if not host:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'host'.",
                    error_code="MISSING_HOST",
                )
            count = self._to_int(params.get("count"), default=4, min_value=1, max_value=10)
            out = sd.net_ping(host, count)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=f"Ping executed for {host} ({count} packets)." if ok else str(out),
                host=host,
                count=count,
                output=out,
            )

        if local == "service.manage":
            unit = str(params.get("unit") or "").strip()
            action = str(params.get("action") or "").strip()
            if not unit or not action:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameters 'unit' and/or 'action'.",
                    error_code="MISSING_SERVICE_PARAMS",
                )
            out = sd.service_action(unit, action)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out) if out else f"Service action '{action}' executed for '{unit}'.",
                unit=unit,
                action=action,
                output=out,
            )

        if local == "service.logs":
            unit = str(params.get("unit") or "").strip()
            if not unit:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'unit'.",
                    error_code="MISSING_UNIT",
                )
            lines = self._to_int(params.get("lines"), default=50, min_value=1, max_value=500)
            out = sd.service_logs(unit, lines)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=f"Service logs retrieved for '{unit}' ({lines} lines)." if ok else str(out),
                unit=unit,
                lines=lines,
                logs=out if ok else None,
                output=out if not ok else None,
            )

        if local == "fs.list":
            path = str(params.get("path") or params.get("filepath") or ".")
            out = sd.fs_list(path)
            if isinstance(out, str) and self._is_error_text(out):
                return self._result(
                    ok=False,
                    status="error",
                    message=str(out),
                    error_code="FS_LIST_FAILED",
                    path=path,
                )
            if isinstance(out, list):
                return self._result(
                    ok=True,
                    status="success" if out else "empty",
                    message=f"Listed {len(out)} items in '{path}'.",
                    path=path,
                    count=len(out),
                    results=out,
                )
            return self._result(
                ok=False,
                status="error",
                message=f"Unexpected fs.list output for '{path}'.",
                error_code="FS_LIST_INVALID_OUTPUT",
                path=path,
                output=out,
            )

        if local == "fs.read":
            path = str(params.get("path") or params.get("filepath") or "").strip()
            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'path'.",
                    error_code="MISSING_PATH",
                )
            start = self._to_int(params.get("start"), default=1, min_value=1)
            end = params.get("end")
            end_value = self._to_int(end, default=start, min_value=start) if end is not None else None
            out = sd.fs_read(path, start, end_value)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=f"Read file '{path}'." if ok else str(out),
                path=path,
                start=start,
                end=end_value,
                content=out if ok else None,
                output=out if not ok else None,
            )

        if local == "fs.write":
            path = str(params.get("path") or params.get("filepath") or "").strip()
            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'path'.",
                    error_code="MISSING_PATH",
                )
            content = str(params.get("content") or "")
            out = sd.fs_write(path, content)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out),
                path=path,
                bytes_written=len(content.encode("utf-8")),
                output=out,
            )

        if local == "fs.delete":
            path = str(params.get("path") or params.get("filepath") or "").strip()
            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'path'.",
                    error_code="MISSING_PATH",
                )
            out = sd.fs_delete(path)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out),
                path=path,
                output=out,
            )

        if local == "keyboard":
            if not pyautogui:
                return self._result(
                    ok=False,
                    status="error",
                    message="Keyboard control (pyautogui) not available.",
                    error_code="PYAUTOGUI_UNAVAILABLE",
                )

            kb_action = self._keyboard_action(params)
            if kb_action == "next":
                pyautogui.hotkey("fn", "right")
                return self._result(ok=True, status="success", message="Skipping to next.", action="next")
            if kb_action == "prev":
                pyautogui.hotkey("fn", "left")
                return self._result(ok=True, status="success", message="Going to previous.", action="prev")
            if kb_action == "pause":
                pyautogui.press("space")
                return self._result(ok=True, status="success", message="Playback paused/resumed.", action="pause")
            if kb_action == "volume_up":
                for _ in range(5):
                    pyautogui.press("volumeup")
                return self._result(ok=True, status="success", message="Volume increased.", action="volume_up")
            if kb_action == "volume_down":
                for _ in range(5):
                    pyautogui.press("volumedown")
                return self._result(ok=True, status="success", message="Volume decreased.", action="volume_down")
            if kb_action == "mute":
                pyautogui.press("volumemute")
                return self._result(ok=True, status="success", message="Mute toggled.", action="mute")
            if kb_action == "close":
                pyautogui.hotkey("alt", "f4")
                return self._result(ok=True, status="success", message="Window closed.", action="close")
            return self._result(
                ok=False,
                status="error",
                message="Unknown keyboard command. Use action: next|prev|pause|volume_up|volume_down|mute|close.",
                error_code="UNKNOWN_KEYBOARD_COMMAND",
            )

        return self._result(
            ok=False,
            status="error",
            message=f"Unknown system action: {action_id}",
            error_code="UNKNOWN_ACTION",
        )
