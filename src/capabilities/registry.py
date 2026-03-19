from typing import Any, Dict, List, Optional, Tuple
import difflib
import hashlib
import logging
import re

from .base import CapabilityBase
from .contract_v1 import CapabilityAction, CapabilityContractV1

logger = logging.getLogger("CapabilityRegistry")


def _get_nested_value(data: Dict[str, Any], path: str) -> Any:
    current: Any = data
    for token in str(path or "").split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(token)
    return current


class CapabilityRegistry:
    def __init__(self):
        self.capabilities: Dict[str, CapabilityBase] = {}
        self.action_map: Dict[str, CapabilityBase] = {}
        self.action_models: Dict[str, CapabilityAction] = {}
        self.capability_contracts: Dict[str, CapabilityContractV1] = {}
        self.retrieval_offers: Dict[str, Dict[str, Any]] = {}
        self.schemas: Dict[str, dict] = {}  # capability folder -> config schema

    def register(self, capability: CapabilityBase, contract: CapabilityContractV1) -> None:
        capability_id = contract.capability.id
        self.capabilities[capability_id] = capability
        self.capability_contracts[capability_id] = contract
        self._index_retrieval_offer(capability=capability, contract=contract)

        for action in contract.actions:
            if action.id in self.action_map:
                logger.warning(
                    "Action '%s' is already registered by capability '%s'. Overwriting with '%s'.",
                    action.id,
                    self.action_map[action.id].name,
                    capability.name,
                )
            self.action_map[action.id] = capability
            self.action_models[action.id] = action
            logger.debug("Registered action '%s' for capability '%s'", action.id, capability.name)

    def _index_retrieval_offer(self, capability: CapabilityBase, contract: CapabilityContractV1) -> None:
        profile = contract.retrieval_profile
        capability_id = contract.capability.id
        config = capability.config if isinstance(getattr(capability, "config", None), dict) else {}
        is_enabled = bool(config.get("enabled", True))
        if not is_enabled:
            self.retrieval_offers.pop(capability_id, None)
            return
        if not profile or not bool(profile.enabled):
            self.retrieval_offers.pop(capability_id, None)
            return

        action_ids = [action.id for action in contract.actions]
        setup = profile.setup.model_dump() if profile.setup else {}
        required_fields = [str(x).strip() for x in (setup.get("required_fields") or []) if str(x).strip()]
        missing_required_fields: List[str] = []
        for field_path in required_fields:
            value = _get_nested_value(config, field_path)
            if value is None:
                missing_required_fields.append(field_path)
                continue
            if isinstance(value, str) and not value.strip():
                missing_required_fields.append(field_path)
                continue
        setup_ready = len(missing_required_fields) == 0

        self.retrieval_offers[capability_id] = {
            "capability_id": capability_id,
            "namespace": contract.capability.namespace,
            "roles": list(profile.roles),
            "domains": list(profile.domains),
            "entity_types": list(profile.entity_types),
            "routing_hints": dict(profile.routing_hints or {}),
            "actions": action_ids,
            "quality": profile.quality.model_dump() if profile.quality else {},
            "freshness": profile.freshness.model_dump() if profile.freshness else {},
            "cost": profile.cost.model_dump() if profile.cost else {},
            "setup": setup,
            "setup_ready": setup_ready,
            "missing_required_fields": missing_required_fields,
            "output_contract": profile.output_contract.model_dump() if profile.output_contract else {},
        }

    def refresh_retrieval_offer(self, capability_id: str) -> None:
        cap_id = str(capability_id or "").strip()
        if not cap_id:
            return
        capability = self.capabilities.get(cap_id)
        contract = self.capability_contracts.get(cap_id)
        if not capability or not contract:
            self.retrieval_offers.pop(cap_id, None)
            return
        self._index_retrieval_offer(capability=capability, contract=contract)

    def refresh_retrieval_offers(self) -> None:
        for capability_id in list(self.capability_contracts.keys()):
            self.refresh_retrieval_offer(capability_id)

    def list_retrieval_offers(
        self,
        *,
        intent: Optional[str] = None,
        domain: Optional[str] = None,
        role: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # Keep runtime retrieval index in sync with live capability config.
        self.refresh_retrieval_offers()
        offers = list(self.retrieval_offers.values())
        if not offers:
            return []

        intent_value = str(intent or "").strip().lower()
        domain_value = str(domain or "").strip().lower()
        role_value = str(role or "").strip().lower()
        entity_value = str(entity_type or "").strip().lower()

        filtered: List[Dict[str, Any]] = []
        for offer in offers:
            if domain_value and domain_value not in offer.get("domains", []):
                continue
            if role_value and role_value not in offer.get("roles", []):
                continue
            if entity_value and entity_value not in offer.get("entity_types", []):
                continue
            if intent_value:
                hints = offer.get("routing_hints") if isinstance(offer.get("routing_hints"), dict) else {}
                preferred = [str(x).strip().lower() for x in (hints.get("preferred_intents") or []) if str(x).strip()]
                avoid = [str(x).strip().lower() for x in (hints.get("avoid_when") or []) if str(x).strip()]
                if intent_value in avoid:
                    continue
                if preferred and intent_value not in preferred:
                    continue
            filtered.append(dict(offer))
        return sorted(filtered, key=lambda row: str(row.get("capability_id") or ""))

    def get_capability_for_action(self, action_id: str) -> Optional[CapabilityBase]:
        return self.action_map.get(action_id)

    def dispatch(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        capability = self.get_capability_for_action(action_id)
        if not capability:
            return {
                "ok": False,
                "status": "error",
                "error_code": "UNKNOWN_ACTION",
                "error_details": f"Action {action_id} is not registered.",
            }
        try:
            result = capability.execute(action_id, params, context)
            return self._validate_result(action_id, capability.name, result)
        except Exception as exc:
            logger.error("Error executing action '%s' in capability '%s': %s", action_id, capability.name, exc)
            return {
                "ok": False,
                "status": "error",
                "error_code": "CAPABILITY_EXECUTION_ERROR",
                "error_details": str(exc),
            }

    def _validate_result(self, action_id: str, capability_name: str, result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        forbidden = {"text", "message", "reply", "legacy_text"}
        found = [key for key in result.keys() if key in forbidden]
        if not found:
            return result
        logger.warning(
            "CONTRACT_VIOLATION: Capability '%s' returned forbidden fields %s for action '%s'. Stripping.",
            capability_name,
            found,
            action_id,
        )
        return {key: value for key, value in result.items() if key not in forbidden}

    def list_actions(self) -> List[str]:
        return sorted(self.action_map.keys())

    def resolve_action_id(self, action_id: str) -> Optional[str]:
        if not action_id:
            return None
        normalized = action_id.strip().lower().replace(" ", ".")
        if normalized in self.action_map:
            return normalized
        actions = list(self.action_map.keys())
        if not actions:
            return None

        local_matches = [aid for aid in actions if aid.split(".")[-1] == normalized]
        if len(local_matches) == 1:
            return local_matches[0]

        prefix_matches = [aid for aid in actions if aid.startswith(normalized) or normalized.startswith(aid)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

        close = difflib.get_close_matches(normalized, actions, n=1, cutoff=0.82)
        return close[0] if close else None

    def suggest_actions(self, action_id: str, limit: int = 3) -> List[str]:
        if not action_id:
            return []
        normalized = action_id.strip().lower().replace(" ", ".")
        actions = list(self.action_map.keys())
        return difflib.get_close_matches(normalized, actions, n=max(1, limit), cutoff=0.5)

    def get_action_metadata(self, action_id: str) -> Dict[str, Any]:
        action = self.action_models.get(action_id)
        if not action:
            return {}
        capability = self.get_capability_for_action(action_id)
        capability_id = ""
        namespace = ""
        if capability:
            for cid, instance in self.capabilities.items():
                if instance is capability:
                    capability_id = cid
                    break
        contract = self.capability_contracts.get(capability_id) if capability_id else None
        assets = contract.capability.assets.model_dump() if contract else None
        if not namespace and "." in action_id:
            namespace = ".".join(action_id.split(".")[:-1])

        return {
            "id": action.id,
            "title": action.title,
            "description": action.description,
            "handler": action.handler,
            "risk_level": action.risk_level,
            "permissions": action.permissions.model_dump(),
            "parameters": action.parameters,
            "side_effect": action.side_effect or "none",
            "namespace": namespace,
            "capability_id": capability_id,
            "assets": assets,
        }

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
        return [token for token in tokens if len(token) > 2]

    def _lexical_score(self, user_input: str, action_id: str, description: str) -> Tuple[float, str]:
        tokens_input = self._tokenize(user_input)
        if not tokens_input:
            return 0.0, "empty_input"

        corpus = f"{action_id} {description}".strip()
        tokens_action = self._tokenize(corpus)
        if not tokens_action:
            return 0.0, "empty_action_tokens"

        overlap = len(set(tokens_input) & set(tokens_action))
        overlap_ratio = overlap / max(1, len(set(tokens_input)))
        action_suffix = action_id.split(".")[-1]
        lower_input = (user_input or "").lower()
        exact_boost = 0.25 if action_suffix in lower_input else 0.0
        dotless_boost = 0.20 if action_id.replace(".", " ") in lower_input else 0.0
        score = min(1.0, overlap_ratio + exact_boost + dotless_boost)
        return score, f"overlap={overlap_ratio:.2f}, exact={exact_boost:.2f}, dotless={dotless_boost:.2f}"

    def get_summary(self, allowed_actions: Optional[List[str]] = None) -> str:
        allowed = set(allowed_actions) if allowed_actions is not None else None
        lines: List[str] = []
        for action_id in sorted(self.action_models.keys()):
            if allowed is not None and action_id not in allowed:
                continue
            action = self.action_models[action_id]
            lines.append(f"- `{action_id}`: {action.description}")
        return "\n".join(lines)

    def get_compact_manifest(self, allowed_actions: Optional[List[str]] = None) -> Dict[str, Any]:
        allowed = set(allowed_actions) if allowed_actions is not None else None
        actions: List[str] = []
        namespaces: set[str] = set()
        for action_id in sorted(self.action_models.keys()):
            if allowed is not None and action_id not in allowed:
                continue
            actions.append(action_id)
            namespaces.add(".".join(action_id.split(".")[:2]) if "." in action_id else action_id)

        digest = hashlib.sha1("\n".join(actions).encode("utf-8")).hexdigest()[:12] if actions else "none"
        return {
            "count": len(actions),
            "hash": digest,
            "namespaces": sorted(namespaces),
            "actions": actions,
        }

    def get_focus_actions(
        self,
        user_input: str,
        allowed_actions: Optional[List[str]] = None,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        allowed = set(allowed_actions) if allowed_actions is not None else None
        ranked: List[Tuple[float, str, str]] = []
        for action_id, action in self.action_models.items():
            if allowed is not None and action_id not in allowed:
                continue
            score, _ = self._lexical_score(user_input or "", action_id, action.description)
            ranked.append((score, action_id, action.description))

        ranked.sort(key=lambda row: (-row[0], row[1]))
        out: List[Dict[str, Any]] = []
        for score, action_id, description in ranked[: max(1, int(limit or 1))]:
            out.append(
                {
                    "id": action_id,
                    "description": description,
                    "score": round(float(score), 3),
                }
            )
        return out

    def get_catalog(
        self,
        allowed_actions: Optional[List[str]] = None,
        include_descriptions: bool = True,
    ) -> List[Dict[str, Any]]:
        allowed = set(allowed_actions) if allowed_actions is not None else None
        out: List[Dict[str, Any]] = []
        for action_id in sorted(self.action_models.keys()):
            if allowed is not None and action_id not in allowed:
                continue
            meta = self.get_action_metadata(action_id)
            row: Dict[str, Any] = {
                "id": action_id,
                "namespace": meta.get("namespace") or ".".join(action_id.split(".")[:2]),
                "risk_level": str(meta.get("risk_level")),
                "capability_id": meta.get("capability_id", ""),
            }
            if include_descriptions:
                row["description"] = str(meta.get("description") or "")
            out.append(row)
        return out
