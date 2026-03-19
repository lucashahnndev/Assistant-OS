import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("UserPreferenceStore")


def _now_ts() -> float:
    return float(time.time())


def _normalize_scope(scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(scope, dict):
        return {"type": "global"}
    scope_type = str(scope.get("type") or "global").strip().lower()
    value = scope.get("value")
    context_tags = scope.get("context_tags")
    normalized: Dict[str, Any] = {"type": scope_type or "global"}
    if value is not None:
        normalized["value"] = str(value).strip()
    if isinstance(context_tags, list):
        tags = [str(t).strip().lower() for t in context_tags if str(t).strip()]
        if tags:
            normalized["context_tags"] = sorted(set(tags))
    return normalized


class UserPreferenceStore:
    """
    Persistent store for explicit user preferences.
    This is Phase-0 (v3): explicit preferences only, no adaptive learning writes.
    """

    def __init__(self, base_path: str):
        # Accept either ".../data" or ".../data/notifications".
        if os.path.basename(base_path.rstrip("/")) == "notifications":
            self.data_dir = base_path
        else:
            self.data_dir = os.path.join(base_path, "notifications")
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "preferences.json")
        self.state: Dict[str, Any] = {
            "schema_version": 1,
            "preference_version": 0,
            "preferences": [],
            "updated_at": _now_ts(),
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            self._save()
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.state.update(loaded)
                self.state.setdefault("schema_version", 1)
                self.state.setdefault("preference_version", 0)
                self.state.setdefault("preferences", [])
                self.state.setdefault("updated_at", _now_ts())
        except Exception as e:
            logger.error("Failed to load preferences store: %s", e)

    def _save(self):
        self.state["updated_at"] = _now_ts()
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save preferences store: %s", e)

    def _next_preference_version(self) -> int:
        current = int(self.state.get("preference_version", 0) or 0)
        nxt = current + 1
        self.state["preference_version"] = nxt
        return nxt

    def get_global_preference_version(self) -> int:
        return int(self.state.get("preference_version", 0) or 0)

    def get_user_preference_version(self, user_id: str) -> int:
        user_prefs = self.list_preferences(user_id=user_id, active_only=False)
        if not user_prefs:
            return self.get_global_preference_version()
        return max(int(p.get("version", 0) or 0) for p in user_prefs)

    def list_preferences(
        self,
        *,
        user_id: str,
        dimension: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        prefs = self.state.get("preferences", [])
        if not isinstance(prefs, list):
            return []
        out: List[Dict[str, Any]] = []
        dim = str(dimension or "").strip().lower()
        for pref in prefs:
            if not isinstance(pref, dict):
                continue
            if str(pref.get("user_id") or "") != str(user_id):
                continue
            if active_only and not bool(pref.get("active", True)):
                continue
            if dim and str(pref.get("dimension") or "").strip().lower() != dim:
                continue
            out.append(pref)
        out.sort(key=lambda p: int(p.get("version", 0) or 0), reverse=True)
        return out

    @staticmethod
    def _scope_matches(
        scope: Dict[str, Any],
        *,
        domain: Optional[str],
        event_type: Optional[str],
        context_tags: Optional[List[str]],
    ) -> bool:
        scope_type = str(scope.get("type") or "global").strip().lower()
        scope_value = str(scope.get("value") or "").strip().lower()
        if scope_type in {"", "global"}:
            return True
        if scope_type == "domain":
            return bool(domain) and str(domain).strip().lower() == scope_value
        if scope_type == "event_type":
            return bool(event_type) and str(event_type).strip().lower() == scope_value
        if scope_type == "context":
            tags = [str(t).strip().lower() for t in (context_tags or []) if str(t).strip()]
            scoped_tags = [
                str(t).strip().lower()
                for t in list(scope.get("context_tags") or [])
                if str(t).strip()
            ]
            return bool(set(tags) & set(scoped_tags))
        return False

    def get_effective_preferences(
        self,
        *,
        user_id: str,
        domain: Optional[str] = None,
        event_type: Optional[str] = None,
        context_tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        all_user = self.list_preferences(user_id=user_id, active_only=True)
        matched = []
        for pref in all_user:
            scope = _normalize_scope(pref.get("scope") if isinstance(pref.get("scope"), dict) else None)
            if self._scope_matches(scope, domain=domain, event_type=event_type, context_tags=context_tags):
                p = dict(pref)
                p["scope"] = scope
                matched.append(p)
        # Hard constraints first, then most recent.
        matched.sort(
            key=lambda p: (
                0 if str(p.get("priority") or "soft").strip().lower() == "hard" else 1,
                -int(p.get("version", 0) or 0),
            )
        )
        return matched

    def upsert_preference(
        self,
        *,
        user_id: str,
        dimension: str,
        key: str,
        value: Any,
        scope: Optional[Dict[str, Any]],
        priority: str = "hard",
        source: str = "explicit_user_command",
        impact_level: str = "low",
    ) -> Dict[str, Any]:
        normalized_scope = _normalize_scope(scope)
        dim = str(dimension or "").strip().lower()
        normalized_key = str(key or "").strip().lower()
        normalized_priority = str(priority or "hard").strip().lower()
        normalized_source = str(source or "explicit_user_command").strip().lower()
        normalized_impact = str(impact_level or "low").strip().lower()
        version = self._next_preference_version()
        now = _now_ts()

        prefs = self.state.get("preferences")
        if not isinstance(prefs, list):
            prefs = []
            self.state["preferences"] = prefs

        for pref in prefs:
            if not isinstance(pref, dict):
                continue
            if str(pref.get("user_id") or "") != str(user_id):
                continue
            if str(pref.get("dimension") or "").strip().lower() != dim:
                continue
            if str(pref.get("key") or "").strip().lower() != normalized_key:
                continue
            existing_scope = _normalize_scope(pref.get("scope") if isinstance(pref.get("scope"), dict) else None)
            if existing_scope != normalized_scope:
                continue
            pref["value"] = value
            pref["priority"] = normalized_priority
            pref["source"] = normalized_source
            pref["impact_level"] = normalized_impact
            pref["updated_at"] = now
            pref["version"] = version
            pref["active"] = True
            self._save()
            return pref

        record = {
            "preference_id": f"pref_{uuid.uuid4().hex[:10]}",
            "user_id": str(user_id),
            "dimension": dim,
            "key": normalized_key,
            "value": value,
            "scope": normalized_scope,
            "priority": normalized_priority,
            "source": normalized_source,
            "impact_level": normalized_impact,
            "active": True,
            "created_at": now,
            "updated_at": now,
            "version": version,
        }
        prefs.append(record)
        self._save()
        return record
