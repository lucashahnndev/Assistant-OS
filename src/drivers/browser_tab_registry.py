from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


TabPurpose = str  # media|task|user
TabStatus = str   # idle|busy|user_controlled|closed


@dataclass
class TabRecord:
    tab_id: str
    page_ref: Any
    purpose: TabPurpose = "task"
    status: TabStatus = "idle"
    device_id: Optional[str] = None
    owner_task_id: Optional[str] = None
    pinned: bool = False
    last_url: str = ""
    last_verified_at: Optional[str] = None
    last_verification_source: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self, url: Optional[str] = None) -> None:
        self.last_used_at = datetime.now(timezone.utc).isoformat()
        if url is not None:
            self.last_url = str(url)


class TabRegistry:
    """In-memory tab registry; intentionally reset on process restart."""

    def __init__(self) -> None:
        self._tabs: Dict[str, TabRecord] = {}
        self._page_index: Dict[int, str] = {}
        self._media_slots: Dict[str, str] = {}

    def clear(self) -> None:
        self._tabs.clear()
        self._page_index.clear()
        self._media_slots.clear()

    @staticmethod
    def _page_key(page_ref: Any) -> int:
        return id(page_ref)

    def register_tab(
        self,
        tab_id: str,
        page_ref: Any,
        purpose: TabPurpose = "task",
        status: TabStatus = "idle",
        device_id: Optional[str] = None,
        owner_task_id: Optional[str] = None,
        pinned: bool = False,
    ) -> TabRecord:
        existing = self.get_by_page(page_ref)
        if existing:
            existing.purpose = purpose or existing.purpose
            existing.status = status or existing.status
            existing.device_id = device_id if device_id is not None else existing.device_id
            existing.owner_task_id = owner_task_id if owner_task_id is not None else existing.owner_task_id
            existing.pinned = pinned
            existing.touch(url=getattr(page_ref, "url", ""))
            return existing

        record = TabRecord(
            tab_id=tab_id,
            page_ref=page_ref,
            purpose=purpose,
            status=status,
            device_id=device_id,
            owner_task_id=owner_task_id,
            pinned=pinned,
            last_url=str(getattr(page_ref, "url", "") or ""),
        )
        self._tabs[tab_id] = record
        self._page_index[self._page_key(page_ref)] = tab_id
        return record

    def get(self, tab_id: Optional[str]) -> Optional[TabRecord]:
        if not tab_id:
            return None
        rec = self._tabs.get(tab_id)
        if rec and rec.status != "closed":
            return rec
        return None

    def get_by_page(self, page_ref: Any) -> Optional[TabRecord]:
        tab_id = self._page_index.get(self._page_key(page_ref))
        return self.get(tab_id)

    def set_media_slot(self, device_id: str, tab_id: Optional[str]) -> None:
        if not tab_id:
            self._media_slots.pop(device_id, None)
            return
        self._media_slots[device_id] = tab_id

    def get_media_slot(self, device_id: str) -> Optional[TabRecord]:
        tab_id = self._media_slots.get(device_id)
        rec = self.get(tab_id)
        if rec:
            return rec
        if tab_id:
            self._media_slots.pop(device_id, None)
        return None

    def touch(self, tab_id: str, url: Optional[str] = None) -> None:
        rec = self.get(tab_id)
        if rec:
            rec.touch(url=url)

    def mark_status(self, tab_id: str, status: TabStatus) -> None:
        rec = self.get(tab_id)
        if rec:
            rec.status = status
            rec.touch()

    def mark_verified(self, tab_id: str, source: str) -> None:
        rec = self.get(tab_id)
        if rec:
            rec.last_verified_at = datetime.now(timezone.utc).isoformat()
            rec.last_verification_source = source
            rec.touch()

    def mark_verified_by_page(self, page_ref: Any, source: str) -> None:
        rec = self.get_by_page(page_ref)
        if rec:
            self.mark_verified(rec.tab_id, source)

    def close(self, tab_id: str) -> None:
        rec = self._tabs.get(tab_id)
        if not rec:
            return
        rec.status = "closed"
        self._page_index.pop(self._page_key(rec.page_ref), None)
        # clear media slots pointing to closed tab
        stale = [d for d, t in self._media_slots.items() if t == tab_id]
        for d in stale:
            self._media_slots.pop(d, None)

    def list_open(self) -> list[TabRecord]:
        return [r for r in self._tabs.values() if r.status != "closed"]

    def find_idle(self, purpose: str) -> Optional[TabRecord]:
        candidates = [
            r for r in self._tabs.values()
            if r.status == "idle" and r.purpose == purpose
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.last_used_at, reverse=True)
        return candidates[0]

    def count_open(self, purpose: Optional[str] = None) -> int:
        records = self.list_open()
        if purpose is None:
            return len(records)
        return len([r for r in records if r.purpose == purpose])

    def snapshot_media_slots(self) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for device_id, tab_id in list(self._media_slots.items()):
            rec = self.get(tab_id)
            if not rec:
                continue
            result[device_id] = {
                "tab_id": rec.tab_id,
                "status": rec.status,
                "purpose": rec.purpose,
                "url": rec.last_url,
                "last_used_at": rec.last_used_at,
                "last_verified_at": rec.last_verified_at,
                "last_verification_source": rec.last_verification_source,
            }
        return result
