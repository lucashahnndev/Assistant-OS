import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_epoch_seconds(value: Any) -> int:
    try:
        if isinstance(value, (int, float)):
            return int(value)
        if not value:
            return 0
        text = str(value).strip()
        if not text:
            return 0
        # Normalize trailing Z for fromisoformat
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


class BrowserSessionRegistry:
    """
    Global registry for browser instances and tabs.
    Persisted in JSON and safe for multi-thread access in-process.
    """

    def __init__(self, base_data_dir: Optional[str] = None, filename: str = "browser_registry.json"):
        root = base_data_dir or "data"
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, filename)
        self._lock = threading.RLock()
        self._boot_id = f"boot_{int(time.time())}_{os.getpid()}"
        self._state = self._load_or_init()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "boot_id": self._boot_id,
            "updated_at": _utc_now(),
            "instances": {},
        }

    def _load_or_init(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            state = self._default_state()
            self._save_state(state)
            return state
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Registry file is not a JSON object")
            if "instances" not in data or not isinstance(data.get("instances"), dict):
                data["instances"] = {}
            data.setdefault("version", 1)
            data["boot_id"] = self._boot_id
            data["updated_at"] = _utc_now()
            self._save_state(data)
            return data
        except Exception:
            state = self._default_state()
            self._save_state(state)
            return state

    def _save_state(self, data: Dict[str, Any]) -> None:
        data["updated_at"] = _utc_now()
        tmp = f"{self.path}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def reset_active_indexes_on_boot(self) -> Dict[str, int]:
        """
        Marks active/open resources as stale after service restart.
        """
        with self._lock:
            instances = self._state.get("instances", {})
            stale_instances = 0
            stale_tabs = 0
            for _, inst in instances.items():
                status = str(inst.get("status", "")).lower()
                if status in {"active", "running", "open"}:
                    inst["status"] = "stale"
                    stale_instances += 1
                inst["in_use"] = False
                inst["last_heartbeat_at"] = _utc_now()
                tabs = inst.get("tabs", {})
                if isinstance(tabs, dict):
                    for _, tab in tabs.items():
                        tab_status = str(tab.get("status", "")).lower()
                        if tab_status in {"active", "open", "attached"}:
                            tab["status"] = "stale"
                            stale_tabs += 1
                        tab["in_use"] = False
                        tab["last_seen_at"] = _utc_now()
            self._state["boot_id"] = self._boot_id
            self._save_state(self._state)
            return {"stale_instances": stale_instances, "stale_tabs": stale_tabs}


    def register_instance(
        self,
        *,
        owner_session_id: str,
        work_id: str,
        intent_class: str,
        debug_port: Optional[int],
        cdp_ws_url: Optional[str],
        mcp_endpoint: Optional[str] = None,
        mcp_port: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            instance_id = f"chrome_{uuid.uuid4().hex[:10]}"
            self._state["instances"][instance_id] = {
                "instance_id": instance_id,
                "owner_session_id": owner_session_id,
                "work_id": work_id,
                "intent_class": intent_class,
                "debug_port": debug_port,
                "cdp_ws_url": cdp_ws_url or "",
                "mcp_endpoint": str(mcp_endpoint or ""),
                "mcp_port": int(mcp_port) if isinstance(mcp_port, int) else None,
                "status": "active",
                "in_use": True,
                "created_at": _utc_now(),
                "last_heartbeat_at": _utc_now(),
                "tabs": {},
                "metadata": metadata or {},
            }
            self._save_state(self._state)
            return instance_id

    def update_instance(self, instance_id: str, **patch: Any) -> None:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return
            inst.update({k: v for k, v in patch.items() if v is not None})
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)

    def get_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return None
            return dict(inst)

    def close_instance(self, instance_id: str, reason: str = "") -> None:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return
            inst["status"] = "closed"
            inst["in_use"] = False
            inst["closed_at"] = _utc_now()
            if reason:
                inst["close_reason"] = reason
            tabs = inst.get("tabs", {})
            if isinstance(tabs, dict):
                for _, tab in tabs.items():
                    tab["status"] = "closed"
                    tab["in_use"] = False
                    tab["closed_at"] = _utc_now()
            self._save_state(self._state)

    def list_instances(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._state.get("instances", {}).values()]

    def register_tab(
        self,
        *,
        instance_id: str,
        target_id: str,
        url: str,
        title: str,
        role: str = "generic",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return None
            tabs = inst.setdefault("tabs", {})
            if not isinstance(tabs, dict):
                tabs = {}
                inst["tabs"] = tabs
            # Reuse existing tab by target_id
            for existing_id, tab in tabs.items():
                if isinstance(tab, dict) and str(tab.get("target_id")) == str(target_id):
                    tab["url"] = url
                    tab["title"] = title
                    tab["role"] = role or tab.get("role", "generic")
                    tab["in_use"] = True
                    tab["status"] = "active"
                    tab["last_seen_at"] = _utc_now()
                    self._save_state(self._state)
                    return existing_id

            tab_id = f"tab_{uuid.uuid4().hex[:10]}"
            tabs[tab_id] = {
                "tab_id": tab_id,
                "target_id": target_id,
                "url": url,
                "title": title,
                "role": role or "generic",
                "status": "active",
                "in_use": True,
                "created_at": _utc_now(),
                "last_seen_at": _utc_now(),
                "metadata": metadata or {},
            }
            self._save_state(self._state)
            return tab_id

    def update_tab(self, instance_id: str, tab_id: str, **patch: Any) -> None:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                return
            tab = tabs.get(tab_id)
            if not isinstance(tab, dict):
                return
            tab.update({k: v for k, v in patch.items() if v is not None})
            tab["last_seen_at"] = _utc_now()
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)

    def close_tab(self, instance_id: str, tab_id: str, reason: str = "") -> None:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                return
            tab = tabs.get(tab_id)
            if not isinstance(tab, dict):
                return
            tab["status"] = "closed"
            tab["in_use"] = False
            tab["closed_at"] = _utc_now()
            if reason:
                tab["close_reason"] = reason
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)

    def list_tabs(self, instance_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return []
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                return []
            return [dict(v) for v in tabs.values() if isinstance(v, dict)]

    def get_tab(self, instance_id: str, tab_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return None
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                return None
            tab = tabs.get(tab_id)
            if not isinstance(tab, dict):
                return None
            return dict(tab)

    def close_other_media_instances(self, owner_session_id: str, keep_instance_id: Optional[str] = None) -> int:
        details = self.close_other_media_instances_detailed(owner_session_id, keep_instance_id=keep_instance_id)
        return int(details.get("closed", 0))

    def close_other_media_instances_detailed(self, owner_session_id: str, keep_instance_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Enforces a media singleton per owner session by closing active media instances
        except the one identified by keep_instance_id.
        """
        closed = 0
        closed_instances: List[Dict[str, Any]] = []
        with self._lock:
            instances = self._state.get("instances", {})
            for instance_id, inst in instances.items():
                if not isinstance(inst, dict):
                    continue
                if keep_instance_id and instance_id == keep_instance_id:
                    continue
                if str(inst.get("owner_session_id", "")) != str(owner_session_id):
                    continue
                status = str(inst.get("status", "")).lower()
                if status not in {"active", "running", "open"}:
                    continue
                if str(inst.get("intent_class", "")).lower() != "controlar_midia":
                    continue
                tabs = inst.get("tabs", {})
                tabs_snapshot = list(tabs.values()) if isinstance(tabs, dict) else []
                closed_instances.append(
                    {
                        "instance_id": instance_id,
                        "debug_port": inst.get("debug_port"),
                        "cdp_ws_url": inst.get("cdp_ws_url"),
                        "tabs": tabs_snapshot,
                    }
                )
                inst["status"] = "closed"
                inst["in_use"] = False
                inst["closed_at"] = _utc_now()
                inst["close_reason"] = "media_singleton_replaced"
                if isinstance(tabs, dict):
                    for _, tab in tabs.items():
                        if isinstance(tab, dict):
                            tab["status"] = "closed"
                            tab["in_use"] = False
                            tab["closed_at"] = _utc_now()
                            tab["close_reason"] = "media_singleton_replaced"
                closed += 1
            if closed:
                self._save_state(self._state)
        return {"closed": closed, "instances": closed_instances}

    def acquire_instance_lock(
        self,
        instance_id: str,
        *,
        owner_session_id: str,
        work_id: str,
        lease_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Acquires (or refreshes) a logical execution lock for an instance.
        Lock is granted if:
        - no active lock exists
        - existing lock is expired
        - existing lock belongs to same session/work
        """
        now = int(time.time())
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return {"ok": False, "reason": "instance_not_found"}

            session = str(owner_session_id or "")
            work = str(work_id or "")
            if not session or not work:
                return {"ok": False, "reason": "invalid_owner"}

            lock = inst.get("lock")
            if not isinstance(lock, dict):
                lock = {}
            locked_by_session = str(lock.get("owner_session_id", "") or "")
            locked_by_work = str(lock.get("work_id", "") or "")
            expires_at = int(lock.get("expires_at", 0) or 0)
            active = bool(lock.get("active", False)) and expires_at > now

            if active and (locked_by_session != session or locked_by_work != work):
                return {
                    "ok": False,
                    "reason": "locked_by_other_work",
                    "lock": {
                        "owner_session_id": locked_by_session,
                        "work_id": locked_by_work,
                        "expires_at": expires_at,
                    },
                }

            inst["lock"] = {
                "active": True,
                "owner_session_id": session,
                "work_id": work,
                "acquired_at": lock.get("acquired_at") or _utc_now(),
                "last_heartbeat_at": _utc_now(),
                "expires_at": now + max(30, int(lease_seconds or 300)),
            }
            inst["in_use"] = True
            inst["owner_session_id"] = session
            inst["work_id"] = work
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)
            return {"ok": True, "reason": "acquired", "lock": dict(inst["lock"])}

    def release_instance_lock(self, instance_id: str, *, owner_session_id: str, work_id: str, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return {"ok": False, "reason": "instance_not_found"}

            lock = inst.get("lock")
            if not isinstance(lock, dict):
                return {"ok": True, "reason": "not_locked"}

            session = str(owner_session_id or "")
            work = str(work_id or "")
            locked_by_session = str(lock.get("owner_session_id", "") or "")
            locked_by_work = str(lock.get("work_id", "") or "")

            if not force and (locked_by_session != session or locked_by_work != work):
                return {"ok": False, "reason": "lock_owned_by_other"}

            lock["active"] = False
            lock["released_at"] = _utc_now()
            lock["expires_at"] = int(time.time())
            inst["in_use"] = False
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)
            return {"ok": True, "reason": "released"}

    def acquire_tab_lock(
        self,
        instance_id: str,
        tab_id: str,
        *,
        owner_session_id: str,
        work_id: str,
        lease_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Acquires (or refreshes) a logical execution lock for a tab.
        """
        now = int(time.time())
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return {"ok": False, "reason": "instance_not_found"}
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                return {"ok": False, "reason": "tab_not_found"}
            tab = tabs.get(tab_id)
            if not isinstance(tab, dict):
                return {"ok": False, "reason": "tab_not_found"}

            session = str(owner_session_id or "")
            work = str(work_id or "")
            if not session or not work:
                return {"ok": False, "reason": "invalid_owner"}

            lock = tab.get("lock")
            if not isinstance(lock, dict):
                lock = {}
            locked_by_session = str(lock.get("owner_session_id", "") or "")
            locked_by_work = str(lock.get("work_id", "") or "")
            expires_at = int(lock.get("expires_at", 0) or 0)
            active = bool(lock.get("active", False)) and expires_at > now

            if active and (locked_by_session != session or locked_by_work != work):
                return {
                    "ok": False,
                    "reason": "tab_locked_by_other_work",
                    "lock": {
                        "owner_session_id": locked_by_session,
                        "work_id": locked_by_work,
                        "expires_at": expires_at,
                    },
                }

            tab["lock"] = {
                "active": True,
                "owner_session_id": session,
                "work_id": work,
                "acquired_at": lock.get("acquired_at") or _utc_now(),
                "last_heartbeat_at": _utc_now(),
                "expires_at": now + max(30, int(lease_seconds or 300)),
            }
            tab["in_use"] = True
            tab["last_seen_at"] = _utc_now()
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)
            return {"ok": True, "reason": "acquired", "lock": dict(tab["lock"])}

    def release_tab_lock(
        self,
        instance_id: str,
        tab_id: str,
        *,
        owner_session_id: str,
        work_id: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            inst = self._state.get("instances", {}).get(instance_id)
            if not isinstance(inst, dict):
                return {"ok": False, "reason": "instance_not_found"}
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                return {"ok": False, "reason": "tab_not_found"}
            tab = tabs.get(tab_id)
            if not isinstance(tab, dict):
                return {"ok": False, "reason": "tab_not_found"}

            lock = tab.get("lock")
            if not isinstance(lock, dict):
                return {"ok": True, "reason": "not_locked"}

            session = str(owner_session_id or "")
            work = str(work_id or "")
            locked_by_session = str(lock.get("owner_session_id", "") or "")
            locked_by_work = str(lock.get("work_id", "") or "")

            if not force and (locked_by_session != session or locked_by_work != work):
                return {"ok": False, "reason": "lock_owned_by_other"}

            lock["active"] = False
            lock["released_at"] = _utc_now()
            lock["expires_at"] = int(time.time())
            tab["in_use"] = False
            tab["last_seen_at"] = _utc_now()
            inst["last_heartbeat_at"] = _utc_now()
            self._save_state(self._state)
            return {"ok": True, "reason": "released"}

    def cleanup_expired_locks(self) -> Dict[str, int]:
        """
        Marks expired instance/tab locks as inactive and releases in_use flags.
        """
        now = int(time.time())
        expired_instance_locks = 0
        expired_tab_locks = 0
        changed = False
        with self._lock:
            instances = self._state.get("instances", {})
            for _, inst in instances.items():
                if not isinstance(inst, dict):
                    continue
                lock = inst.get("lock")
                if isinstance(lock, dict) and bool(lock.get("active", False)):
                    exp = int(lock.get("expires_at", 0) or 0)
                    if exp > 0 and exp <= now:
                        lock["active"] = False
                        lock["released_at"] = _utc_now()
                        inst["in_use"] = False
                        expired_instance_locks += 1
                        changed = True
                tabs = inst.get("tabs", {})
                if isinstance(tabs, dict):
                    for _, tab in tabs.items():
                        if not isinstance(tab, dict):
                            continue
                        tab_lock = tab.get("lock")
                        if isinstance(tab_lock, dict) and bool(tab_lock.get("active", False)):
                            exp = int(tab_lock.get("expires_at", 0) or 0)
                            if exp > 0 and exp <= now:
                                tab_lock["active"] = False
                                tab_lock["released_at"] = _utc_now()
                                tab["in_use"] = False
                                expired_tab_locks += 1
                                changed = True
            if changed:
                self._save_state(self._state)
        return {
            "expired_instance_locks": expired_instance_locks,
            "expired_tab_locks": expired_tab_locks,
        }

    def close_idle_instances(self, idle_seconds: int = 1800, keep_instance_ids: Optional[List[str]] = None) -> Dict[str, int]:
        """
        Closes instances that are active but idle for longer than idle_seconds.
        """
        now = int(time.time())
        threshold = max(60, int(idle_seconds or 1800))
        keep = {str(i) for i in (keep_instance_ids or []) if str(i).strip()}
        closed_instances = 0
        closed_tabs = 0
        changed = False
        with self._lock:
            instances = self._state.get("instances", {})
            for instance_id, inst in instances.items():
                if not isinstance(inst, dict):
                    continue
                if instance_id in keep:
                    continue
                status = str(inst.get("status", "")).lower()
                if status not in {"active", "running", "open"}:
                    continue
                if bool(inst.get("in_use", False)):
                    continue
                inst_lock = inst.get("lock")
                if isinstance(inst_lock, dict) and bool(inst_lock.get("active", False)):
                    continue
                last_heartbeat = _to_epoch_seconds(inst.get("last_heartbeat_at"))
                if last_heartbeat <= 0:
                    last_heartbeat = _to_epoch_seconds(inst.get("created_at"))
                if last_heartbeat <= 0:
                    continue
                if now - last_heartbeat < threshold:
                    continue
                inst["status"] = "closed"
                inst["close_reason"] = "idle_gc"
                inst["closed_at"] = _utc_now()
                inst["in_use"] = False
                closed_instances += 1
                changed = True
                tabs = inst.get("tabs", {})
                if isinstance(tabs, dict):
                    for _, tab in tabs.items():
                        if not isinstance(tab, dict):
                            continue
                        tab_status = str(tab.get("status", "")).lower()
                        if tab_status in {"closed", "stale"}:
                            continue
                        tab["status"] = "closed"
                        tab["close_reason"] = "idle_gc"
                        tab["closed_at"] = _utc_now()
                        tab["in_use"] = False
                        closed_tabs += 1
            if changed:
                self._save_state(self._state)
        return {"closed_instances": closed_instances, "closed_tabs": closed_tabs}
