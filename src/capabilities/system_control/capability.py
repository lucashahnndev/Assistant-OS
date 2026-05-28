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
            "mcp.status",
            "mcp.resources",
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

    def _mcp_service(self) -> Any:
        orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
        return getattr(orch, "mcp_integration_service", None)

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
    def _tokenize(text: str) -> List[str]:
        return [token for token in re.findall(r"[a-zA-Z0-9_]+", str(text or "").lower()) if len(token) > 1]

    @classmethod
    def _score_text(cls, query_tokens: List[str], *parts: Any) -> float:
        haystack = " ".join(str(part or "") for part in parts if str(part or "").strip()).lower()
        if not haystack:
            return 0.0
        tokens = list(dict.fromkeys(query_tokens))
        if not tokens:
            return 0.0
        overlap = sum(1 for token in tokens if token in haystack)
        score = overlap / max(1, len(tokens))
        if any(token in haystack for token in tokens[:2]):
            score += 0.15
        return min(1.0, score)

    @staticmethod
    def _candidate_namespace(action_id: str) -> str:
        return ".".join(str(action_id or "").split(".")[:-1]) if "." in str(action_id or "") else str(action_id or "")

    def _build_consult_candidates(
        self,
        *,
        query: str,
        domain: str,
        intent: str,
        limit: int,
        context: Dict[str, Any],
        registry: Any,
    ) -> List[Dict[str, Any]]:
        allowed_actions = context.get("allowed_actions")
        allowed_set = set(allowed_actions) if isinstance(allowed_actions, list) else None
        query_text = str(query or context.get("user_input") or "").strip()
        query_tokens = self._tokenize(query_text)
        domain_text = str(domain or "").strip().lower()
        intent_text = str(intent or "").strip().lower()

        broker = None
        orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
        if orch is not None:
            broker = getattr(orch, "context_broker", None)

        evidence_items: List[Any] = []
        if broker is not None and hasattr(broker, "build_bundle"):
            try:
                bundle = broker.build_bundle(
                    user_input=query_text,
                    session=context.get("session"),
                    capability_registry=registry,
                    allowed_actions=allowed_actions if isinstance(allowed_actions, list) else None,
                    situational_context=context.get("situational_context") if isinstance(context.get("situational_context"), dict) else {},
                    session_context=context.get("session_context") if isinstance(context.get("session_context"), dict) else {},
                    broker_hints={
                        "primary_task_id": context.get("primary_task_id"),
                        "hot_action_namespace": domain_text or context.get("hot_action_namespace") or "",
                    },
                )
                evidence_items = list(getattr(bundle, "evidence_items", None) or [])
                diagnostics = getattr(bundle, "diagnostics", None)
            except Exception:
                evidence_items = []
                diagnostics = None
        else:
            diagnostics = None

        focus_rows = []
        if registry and hasattr(registry, "get_focus_actions"):
            try:
                focus_rows = list(registry.get_focus_actions(query_text, allowed_actions=allowed_actions if isinstance(allowed_actions, list) else None, limit=max(1, int(limit or 1))))
            except Exception:
                focus_rows = []
        focus_action_ids = {str(row.get("id") or "").strip() for row in focus_rows if isinstance(row, dict) and str(row.get("id") or "").strip()}

        candidates_by_action: Dict[str, Dict[str, Any]] = {}

        def _add_candidate(row: Dict[str, Any], score: float, source: str, reason: str, source_rank: int) -> None:
            action_id = str(row.get("action_id") or row.get("id") or "").strip()
            if not action_id:
                return
            if allowed_set is not None and action_id.lower() not in {item.lower() for item in allowed_set}:
                return
            if not score and source != "capability_knowledge_rag":
                return
            candidate = {
                "action_id": action_id,
                "capability_id": str(row.get("capability_id") or "").strip(),
                "namespace": str(row.get("namespace") or self._candidate_namespace(action_id)).strip(),
                "title": str(row.get("title") or row.get("name") or action_id).strip(),
                "summary": str(row.get("summary") or row.get("description") or "").strip(),
                "description": str(row.get("description") or row.get("summary") or "").strip(),
                "risk_level": str(row.get("risk_level") or "low").strip(),
                "setup_ready": bool(row.get("setup_ready", True)),
                "source": source,
                "reason": reason,
                "score": round(max(0.0, min(1.0, score)), 4),
                "_source_rank": source_rank,
            }
            current = candidates_by_action.get(action_id)
            if current is None or candidate["score"] > float(current.get("score") or 0.0) or (
                candidate["score"] == float(current.get("score") or 0.0) and candidate["_source_rank"] < int(current.get("_source_rank") or 99)
            ):
                candidates_by_action[action_id] = candidate

        # 1) Evidence-backed candidates from capability knowledge RAG.
        for item in evidence_items:
            if str(getattr(item, "domain", "")).strip().lower() != "capability_knowledge":
                continue
            metadata = getattr(item, "metadata", {}) if isinstance(getattr(item, "metadata", {}), dict) else {}
            action_id = str(metadata.get("action_id") or "").strip()
            if not action_id:
                continue
            meta_text = " ".join(
                [
                    str(getattr(item, "title", "") or ""),
                    str(getattr(item, "content", "") or ""),
                    str(metadata.get("title", "") or ""),
                    str(metadata.get("description", "") or ""),
                    str(metadata.get("namespace", "") or ""),
                    str(metadata.get("capability_id", "") or ""),
                ]
            )
            score = 0.85 + self._score_text(query_tokens, meta_text, domain_text, intent_text)
            row = {
                "action_id": action_id,
                "capability_id": str(metadata.get("capability_id") or "").strip(),
                "namespace": str(metadata.get("namespace") or self._candidate_namespace(action_id)).strip(),
                "title": str(metadata.get("title") or getattr(item, "title", "") or action_id).strip(),
                "summary": str(metadata.get("description") or getattr(item, "content", "")).strip()[:180],
                "description": str(metadata.get("description") or getattr(item, "content", "")).strip(),
                "risk_level": str(metadata.get("risk_level") or "low").strip(),
                "setup_ready": True,
            }
            if domain_text and domain_text in " ".join([row["namespace"], row["capability_id"], action_id]).lower():
                score += 0.1
            _add_candidate(row, score, "capability_knowledge_rag", "evidence-backed action", 0)

        # 2) Discovery offers from the registry, if available.
        discovery_offers = []
        if registry and hasattr(registry, "list_discovery_offers"):
            try:
                discovery_offers = list(registry.list_discovery_offers(intent=intent_text or None, domain=domain_text or None, role=None, entity_type=None))
            except TypeError:
                try:
                    discovery_offers = list(registry.list_discovery_offers())
                except Exception:
                    discovery_offers = []
            except Exception:
                discovery_offers = []

        if discovery_offers:
            for offer in discovery_offers:
                if not isinstance(offer, dict):
                    continue
                actions = [str(a or "").strip() for a in list(offer.get("actions") or []) if str(a or "").strip()]
                keywords = " ".join(str(x or "") for x in list(offer.get("keywords") or []))
                offer_text = " ".join(
                    [
                        str(offer.get("capability_id") or ""),
                        str(offer.get("namespace") or ""),
                        keywords,
                        " ".join(str(x or "") for x in list(offer.get("domains") or [])),
                        " ".join(str(x or "") for x in list(offer.get("entity_types") or [])),
                    ]
                )
                offer_score = self._score_text(query_tokens, offer_text, query_text, domain_text, intent_text)
                if bool(offer.get("setup_ready", True)):
                    offer_score += 0.05
                if domain_text and domain_text in offer_text.lower():
                    offer_score += 0.08
                if diagnostics and domain_text and domain_text in " ".join(getattr(diagnostics, "evidence_domains", []) or []).lower():
                    offer_score += 0.06
                for action_id in actions:
                    if allowed_set is not None and action_id.lower() not in {item.lower() for item in allowed_set}:
                        continue
                    meta = registry.get_action_metadata(action_id) if registry and hasattr(registry, "get_action_metadata") else {}
                    row = {
                        "action_id": action_id,
                        "capability_id": str(offer.get("capability_id") or meta.get("capability_id") or "").strip(),
                        "namespace": str(offer.get("namespace") or meta.get("namespace") or self._candidate_namespace(action_id)).strip(),
                        "title": str(meta.get("title") or offer.get("title") or action_id).strip(),
                        "summary": str(meta.get("description") or offer.get("description") or "").strip(),
                        "description": str(meta.get("description") or offer.get("description") or "").strip(),
                        "risk_level": str(meta.get("risk_level") or offer.get("risk_level") or "low").strip(),
                        "setup_ready": bool(offer.get("setup_ready", True)),
                    }
                    score = offer_score + self._score_text(query_tokens, action_id, row["title"], row["summary"])
                    if action_id in focus_action_ids:
                        score += 0.08
                    _add_candidate(row, score, "retrieval_offer", "registry discovery offer", 1)

        # 3) Focus-ranked actions as a final conservative fallback.
        for focus_row in focus_rows:
            if not isinstance(focus_row, dict):
                continue
            action_id = str(focus_row.get("id") or "").strip()
            if not action_id:
                continue
            if allowed_set is not None and action_id.lower() not in {item.lower() for item in allowed_set}:
                continue
            meta = registry.get_action_metadata(action_id) if registry and hasattr(registry, "get_action_metadata") else {}
            row = {
                "action_id": action_id,
                "capability_id": str(meta.get("capability_id") or "").strip(),
                "namespace": str(meta.get("namespace") or self._candidate_namespace(action_id)).strip(),
                "title": str(meta.get("title") or action_id).strip(),
                "summary": str(meta.get("description") or focus_row.get("description") or "").strip(),
                "description": str(meta.get("description") or focus_row.get("description") or "").strip(),
                "risk_level": str(meta.get("risk_level") or "low").strip(),
                "setup_ready": True,
            }
            score = float(focus_row.get("score") or 0.0) + self._score_text(query_tokens, action_id, row["title"], row["summary"])
            if domain_text and domain_text in " ".join([row["namespace"], row["capability_id"], action_id]).lower():
                score += 0.05
            _add_candidate(row, score, "focus_ranker", "focus-ranked fallback", 2)

        # Conservative fallback: consult the canonical catalog only if discovery offers did not produce candidates.
        if not candidates_by_action and registry and hasattr(registry, "list_actions"):
            for action_id in list(registry.list_actions())[: max(10, int(limit or 10) * 2)]:
                action_id = str(action_id or "").strip()
                if not action_id:
                    continue
                if allowed_set is not None and action_id.lower() not in {item.lower() for item in allowed_set}:
                    continue
                meta = registry.get_action_metadata(action_id) if hasattr(registry, "get_action_metadata") else {}
                row = {
                    "action_id": action_id,
                    "capability_id": str(meta.get("capability_id") or "").strip(),
                    "namespace": str(meta.get("namespace") or self._candidate_namespace(action_id)).strip(),
                    "title": str(meta.get("title") or action_id).strip(),
                    "summary": str(meta.get("description") or "").strip(),
                    "description": str(meta.get("description") or "").strip(),
                    "risk_level": str(meta.get("risk_level") or "low").strip(),
                    "setup_ready": True,
                }
                score = self._score_text(query_tokens, action_id, row["title"], row["summary"], query_text, domain_text, intent_text)
                _add_candidate(row, score, "catalog_fallback", "canonical catalog fallback", 3)

        candidates = list(candidates_by_action.values())
        candidates.sort(key=lambda row: (-float(row.get("score") or 0.0), int(row.get("_source_rank") or 99), str(row.get("action_id") or "")))
        for item in candidates:
            item.pop("_source_rank", None)
        return candidates[: max(1, int(limit or 1))]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        local = self._local_action(action_id)

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

        if local == "consult_tools":
            orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
            registry = getattr(orch, "capability_registry", None)
            if not registry:
                return self._result(
                    ok=False,
                    status="error",
                    message="Capability registry not available.",
                    error_code="SKILL_REGISTRY_UNAVAILABLE",
                )

            query = str(params.get("query") or context.get("user_input") or "").strip()
            domain = str(params.get("domain") or "").strip()
            intent = str(params.get("intent") or "").strip()
            role = str(params.get("role") or "").strip()
            entity_type = str(params.get("entity_type") or "").strip()
            output_format = str(params.get("format") or "legacy").strip().lower()
            limit = self._to_int(params.get("limit"), default=5, min_value=1, max_value=20)

            candidates = self._build_consult_candidates(
                query=query,
                domain=domain,
                intent=intent,
                limit=limit,
                context=context,
                registry=registry,
            )

            diagnostics = None
            broker_domains: List[str] = []
            if orch is not None and hasattr(orch, "context_broker") and orch.context_broker is not None:
                broker = orch.context_broker
                if hasattr(broker, "build_bundle"):
                    try:
                        bundle = broker.build_bundle(
                            user_input=query,
                            session=context.get("session"),
                            capability_registry=registry,
                            allowed_actions=context.get("allowed_actions"),
                            situational_context=context.get("situational_context") if isinstance(context.get("situational_context"), dict) else {},
                            session_context=context.get("session_context") if isinstance(context.get("session_context"), dict) else {},
                            broker_hints=context.get("broker_hints") if isinstance(context.get("broker_hints"), dict) else {},
                        )
                        diagnostics = getattr(bundle, "diagnostics", None)
                        broker_domains = list(getattr(diagnostics, "evidence_domains", []) or [])
                    except Exception:
                        diagnostics = None
                        broker_domains = []

            primary = candidates[0] if candidates else {}
            if output_format == "toon":
                toon_rows = [
                    {
                        "id": row.get("action_id"),
                        "namespace": row.get("namespace"),
                        "risk_level": row.get("risk_level"),
                        "description": row.get("summary") or row.get("description") or "",
                    }
                    for row in candidates
                ]
                toon = encode_capabilities_list(toon_rows, include_description=True)
                return self._result(
                    ok=True,
                    status="success" if candidates else "empty",
                    query=query,
                    intent=intent,
                    domain=domain,
                    role=role,
                    entity_type=entity_type,
                    count=len(candidates),
                    primary_action_id=str(primary.get("action_id") or ""),
                    primary_score=primary.get("score"),
                    discovery_source=str(primary.get("source") or ""),
                    broker_domains=broker_domains,
                    format="toon",
                    audience="ai",
                    toon=toon,
                    items=candidates,
                )

            return self._result(
                ok=True,
                status="success" if candidates else "empty",
                query=query,
                intent=intent,
                domain=domain,
                role=role,
                entity_type=entity_type,
                count=len(candidates),
                items=candidates,
                primary_action_id=str(primary.get("action_id") or ""),
                primary_score=primary.get("score"),
                discovery_source=str(primary.get("source") or ""),
                broker_domains=broker_domains,
                format="legacy",
                audience="ai",
            )

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
                    message=f"Capability discovery returned {len(rows)} action(s).",
                    count=len(rows),
                    items=rows,
                    discovery_mode="on_demand",
                    format="legacy",
                    audience=mode,
                )

            toon = encode_capabilities_list(rows, include_description=include_descriptions)
            return self._result(
                ok=True,
                status="success" if rows else "empty",
                message=f"Capability discovery returned {len(rows)} action(s) in TOON format.",
                count=len(rows),
                toon=toon,
                discovery_mode="on_demand",
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
                resolved = registry.resolve_action_id(action_id) or action_id
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

        if local == "mcp.status":
            service = self._mcp_service()
            if service is None:
                return self._result(
                    ok=False,
                    status="error",
                    message="MCP integration service not available.",
                    error_code="MCP_SERVICE_UNAVAILABLE",
                )
            registry = getattr(service, "server_registry", None)
            servers = []
            if registry and hasattr(registry, "list_all"):
                for server in registry.list_all():
                    resources = getattr(service, "resource_catalog_by_server", {}).get(server.id, {})
                    servers.append(
                        {
                            "id": server.id,
                            "title": server.title,
                            "enabled": bool(server.enabled),
                            "transport": str(server.transport.kind or ""),
                            "endpoint": str(server.transport.endpoint or ""),
                            "command": str(server.transport.command or ""),
                            "trust_tier": str(server.policy.trust_tier or ""),
                            "allow_resources": bool(server.policy.allow_resources),
                            "allow_tool_discovery": bool(server.policy.allow_tool_discovery),
                            "resource_count": len(resources),
                        }
                    )
            refresh_stats = dict(getattr(service, "last_refresh_stats", {}) or {})
            return self._result(
                ok=True,
                status="success" if servers else "empty",
                message=f"MCP status returned for {len(servers)} server(s).",
                count=len(servers),
                servers=servers,
                refresh=refresh_stats,
            )

        if local == "mcp.resources":
            service = self._mcp_service()
            if service is None:
                return self._result(
                    ok=False,
                    status="error",
                    message="MCP integration service not available.",
                    error_code="MCP_SERVICE_UNAVAILABLE",
                )
            server_id = str(params.get("server_id") or "").strip().lower()
            limit = self._to_int(params.get("limit"), default=50, min_value=1, max_value=200)
            rows = service.list_discovered_resources(server_id=server_id)
            query = str(params.get("query") or "").strip().lower()
            if query:
                rows = [
                    row
                    for row in rows
                    if query in str(row.get("uri", "")).lower()
                    or query in str(row.get("name", "")).lower()
                    or query in str(row.get("title", "")).lower()
                    or query in str(row.get("description", "")).lower()
                ]
            rows = rows[:limit]
            return self._result(
                ok=True,
                status="success" if rows else "empty",
                message=f"MCP resources returned: {len(rows)}.",
                count=len(rows),
                items=rows,
                server_id=server_id or "",
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
