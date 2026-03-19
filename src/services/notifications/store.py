import os
import json
import logging
from typing import List, Dict, Optional
from .models import NotificationIntent

logger = logging.getLogger("NotificationStore")

class NotificationStore:
    def __init__(self, base_data_dir: str):
        self.data_dir = os.path.join(base_data_dir, "notifications")
        self.pending_path = os.path.join(self.data_dir, "pending.json")
        self.decision_traces_path = os.path.join(self.data_dir, "decision_traces.json")
        self.learning_signals_path = os.path.join(self.data_dir, "learning_signals.json")
        self.signal_assessments_path = os.path.join(self.data_dir, "signal_assessments.json")
        self.policy_suggestions_path = os.path.join(self.data_dir, "policy_suggestions.json")
        self.policy_patch_queue_path = os.path.join(self.data_dir, "policy_patch_queue.json")
        self.policy_applied_path = os.path.join(self.data_dir, "policy_applied.json")
        self.policy_runtime_overrides_path = os.path.join(self.data_dir, "policy_runtime_overrides.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.pending_notifications: List[Dict] = []
        self.decision_traces: List[Dict] = []
        self.learning_signals: List[Dict] = []
        self.signal_assessments: List[Dict] = []
        self.policy_suggestions: List[Dict] = []
        self.policy_patch_queue: List[Dict] = []
        self.policy_applied: List[Dict] = []
        self.policy_runtime_overrides: Dict[str, Dict[str, Dict]] = {"users": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.pending_path):
            try:
                with open(self.pending_path, 'r', encoding='utf-8') as f:
                    self.pending_notifications = json.load(f)
            except Exception as e:
                logger.error(f"Error loading pending notifications: {e}")
                self.pending_notifications = []
        if os.path.exists(self.decision_traces_path):
            try:
                with open(self.decision_traces_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    self.decision_traces = loaded
            except Exception as e:
                logger.error(f"Error loading decision traces: {e}")
                self.decision_traces = []
        if os.path.exists(self.learning_signals_path):
            try:
                with open(self.learning_signals_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    self.learning_signals = loaded
            except Exception as e:
                logger.error(f"Error loading learning signals: {e}")
                self.learning_signals = []
        if os.path.exists(self.signal_assessments_path):
            try:
                with open(self.signal_assessments_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    self.signal_assessments = loaded
            except Exception as e:
                logger.error(f"Error loading signal assessments: {e}")
                self.signal_assessments = []
        if os.path.exists(self.policy_suggestions_path):
            try:
                with open(self.policy_suggestions_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    self.policy_suggestions = loaded
            except Exception as e:
                logger.error(f"Error loading policy suggestions: {e}")
                self.policy_suggestions = []
        if os.path.exists(self.policy_patch_queue_path):
            try:
                with open(self.policy_patch_queue_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    self.policy_patch_queue = loaded
            except Exception as e:
                logger.error(f"Error loading policy patch queue: {e}")
                self.policy_patch_queue = []
        if os.path.exists(self.policy_applied_path):
            try:
                with open(self.policy_applied_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    self.policy_applied = loaded
            except Exception as e:
                logger.error(f"Error loading applied policy patches: {e}")
                self.policy_applied = []
        if os.path.exists(self.policy_runtime_overrides_path):
            try:
                with open(self.policy_runtime_overrides_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.policy_runtime_overrides = loaded
            except Exception as e:
                logger.error(f"Error loading runtime overrides: {e}")
                self.policy_runtime_overrides = {"users": {}}

    def _save(self):
        try:
            with open(self.pending_path, 'w', encoding='utf-8') as f:
                json.dump(self.pending_notifications, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving pending notifications: {e}")
        try:
            with open(self.decision_traces_path, 'w', encoding='utf-8') as f:
                json.dump(self.decision_traces[-2000:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving decision traces: {e}")
        try:
            with open(self.learning_signals_path, 'w', encoding='utf-8') as f:
                json.dump(self.learning_signals[-5000:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving learning signals: {e}")
        try:
            with open(self.signal_assessments_path, 'w', encoding='utf-8') as f:
                json.dump(self.signal_assessments[-5000:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving signal assessments: {e}")
        try:
            with open(self.policy_suggestions_path, 'w', encoding='utf-8') as f:
                json.dump(self.policy_suggestions[-5000:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving policy suggestions: {e}")
        try:
            with open(self.policy_patch_queue_path, 'w', encoding='utf-8') as f:
                json.dump(self.policy_patch_queue[-5000:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving policy patch queue: {e}")
        try:
            with open(self.policy_applied_path, 'w', encoding='utf-8') as f:
                json.dump(self.policy_applied[-5000:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving applied policy patches: {e}")
        try:
            with open(self.policy_runtime_overrides_path, 'w', encoding='utf-8') as f:
                json.dump(self.policy_runtime_overrides, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving runtime overrides: {e}")

    def add_pending(self, intent: NotificationIntent):
        self.pending_notifications.append(intent.to_dict())
        self._save()

    def get_pending_for_user(self, user_id: str) -> List[NotificationIntent]:
        return [
            NotificationIntent(**n) 
            for n in self.pending_notifications 
            if n.get("target_user_id") == user_id
        ]

    def remove_intent(self, intent_id: str):
        self.pending_notifications = [
            n for n in self.pending_notifications 
            if n.get("intent_id") != intent_id
        ]
        self._save()

    def add_decision_trace(self, trace: Dict):
        if not isinstance(trace, dict):
            return
        self.decision_traces.append(trace)
        self._save()

    def list_decision_traces(
        self,
        *,
        user_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        rows = self.decision_traces if isinstance(self.decision_traces, list) else []
        out: List[Dict] = []
        uid = str(user_id or "").strip()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if uid and str(row.get("target_user_id") or "").strip() != uid:
                continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def add_learning_signal(self, signal: Dict):
        if not isinstance(signal, dict):
            return
        self.learning_signals.append(signal)
        self._save()

    def add_signal_assessment(self, assessment: Dict):
        if not isinstance(assessment, dict):
            return
        self.signal_assessments.append(assessment)
        self._save()

    def get_learning_signal(self, signal_id: str) -> Optional[Dict]:
        sid = str(signal_id or "").strip()
        if not sid:
            return None
        for row in reversed(self.learning_signals):
            if not isinstance(row, dict):
                continue
            if str(row.get("signal_id") or "").strip() == sid:
                return row
        return None

    def get_signal_assessment(self, assessment_id: str) -> Optional[Dict]:
        aid = str(assessment_id or "").strip()
        if not aid:
            return None
        for row in reversed(self.signal_assessments):
            if not isinstance(row, dict):
                continue
            if str(row.get("assessment_id") or "").strip() == aid:
                return row
        return None

    def list_learning_signals(
        self,
        *,
        user_id: Optional[str] = None,
        signal_name: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        rows = self.learning_signals if isinstance(self.learning_signals, list) else []
        out: List[Dict] = []
        uname = str(user_id or "").strip()
        sname = str(signal_name or "").strip().lower()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if uname and str(row.get("user_id") or "").strip() != uname:
                continue
            if sname and str(row.get("signal_name") or "").strip().lower() != sname:
                continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def list_signal_assessments(
        self,
        *,
        user_id: Optional[str] = None,
        signal_name: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        rows = self.signal_assessments if isinstance(self.signal_assessments, list) else []
        out: List[Dict] = []
        uname = str(user_id or "").strip()
        sname = str(signal_name or "").strip().lower()
        signal_index = {str(s.get("signal_id") or ""): s for s in self.learning_signals if isinstance(s, dict)}
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if sname and str(row.get("signal_name") or "").strip().lower() != sname:
                continue
            if uname:
                sig = signal_index.get(str(row.get("signal_id") or ""))
                if not sig or str(sig.get("user_id") or "").strip() != uname:
                    continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_signal_history(
        self,
        *,
        user_id: str,
        signal_name: str,
        lookback_days: int = 30,
    ) -> List[Dict]:
        import time
        now = float(time.time())
        cutoff = now - (max(1, int(lookback_days)) * 86400.0)
        name = str(signal_name or "").strip().lower()
        uid = str(user_id or "").strip()
        rows = []
        for row in self.learning_signals:
            if not isinstance(row, dict):
                continue
            if str(row.get("user_id") or "").strip() != uid:
                continue
            if str(row.get("signal_name") or "").strip().lower() != name:
                continue
            ts = float(row.get("created_at") or 0.0)
            if ts < cutoff:
                continue
            rows.append(row)
        rows.sort(key=lambda r: float(r.get("created_at") or 0.0), reverse=True)
        return rows

    def add_policy_suggestion(self, suggestion: Dict) -> Dict:
        if not isinstance(suggestion, dict):
            return {}
        fp = str(suggestion.get("fingerprint") or "").strip()
        status = str(suggestion.get("status") or "pending").strip().lower()
        if fp and status == "pending":
            for existing in self.policy_suggestions:
                if not isinstance(existing, dict):
                    continue
                if str(existing.get("fingerprint") or "").strip() != fp:
                    continue
                if str(existing.get("status") or "pending").strip().lower() == "pending":
                    return existing
        self.policy_suggestions.append(suggestion)
        self._save()
        return suggestion

    def list_policy_suggestions(
        self,
        *,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        rows = self.policy_suggestions if isinstance(self.policy_suggestions, list) else []
        out: List[Dict] = []
        uid = str(user_id or "").strip()
        st = str(status or "").strip().lower()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if uid and str(row.get("user_id") or "").strip() != uid:
                continue
            if st and str(row.get("status") or "").strip().lower() != st:
                continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_policy_suggestion(self, suggestion_id: str) -> Optional[Dict]:
        sid = str(suggestion_id or "").strip()
        if not sid:
            return None
        for row in reversed(self.policy_suggestions):
            if not isinstance(row, dict):
                continue
            if str(row.get("suggestion_id") or "").strip() == sid:
                return row
        return None

    def review_policy_suggestion(
        self,
        *,
        suggestion_id: str,
        decision: str,
        reviewer: str,
        reason: str = "",
    ) -> Optional[Dict]:
        sid = str(suggestion_id or "").strip()
        dec = str(decision or "").strip().lower()
        if dec not in {"approved", "rejected"}:
            return None
        for row in self.policy_suggestions:
            if not isinstance(row, dict):
                continue
            if str(row.get("suggestion_id") or "").strip() != sid:
                continue
            row["status"] = dec
            row["reviewed_at"] = __import__("time").time()
            row["reviewed_by"] = str(reviewer or "system")
            if reason:
                row["review_reason"] = str(reason)
            if dec == "approved":
                self.add_policy_patch_candidate_from_suggestion(
                    suggestion=row,
                    reviewer=reviewer,
                )
            self._save()
            return row
        return None

    def add_policy_patch_candidate_from_suggestion(self, *, suggestion: Dict, reviewer: str = "user") -> Dict:
        if not isinstance(suggestion, dict):
            return {}
        suggestion_id = str(suggestion.get("suggestion_id") or "").strip()
        if not suggestion_id:
            return {}
        for existing in self.policy_patch_queue:
            if not isinstance(existing, dict):
                continue
            if str(existing.get("source_suggestion_id") or "").strip() == suggestion_id:
                return existing
        import time
        import uuid
        patch = {
            "patch_id": f"ppc_{uuid.uuid4().hex[:10]}",
            "created_at": float(time.time()),
            "status": "pending",
            "mode": "manual_only",
            "source_suggestion_id": suggestion_id,
            "user_id": str(suggestion.get("user_id") or ""),
            "target": str(suggestion.get("target") or ""),
            "proposal": suggestion.get("proposal") if isinstance(suggestion.get("proposal"), dict) else {},
            "reason": str(suggestion.get("reason") or ""),
            "confidence_score": float(suggestion.get("confidence_score") or 0.0),
            "policy_version": suggestion.get("policy_version"),
            "preference_version": suggestion.get("preference_version"),
            "approved_by": str(reviewer or "user"),
            "apply_ready": False,
        }
        self.policy_patch_queue.append(patch)
        self._save()
        return patch

    def list_policy_patch_candidates(
        self,
        *,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        rows = self.policy_patch_queue if isinstance(self.policy_patch_queue, list) else []
        out: List[Dict] = []
        uid = str(user_id or "").strip()
        st = str(status or "").strip().lower()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if uid and str(row.get("user_id") or "").strip() != uid:
                continue
            if st and str(row.get("status") or "").strip().lower() != st:
                continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_policy_patch_candidate(self, patch_id: str) -> Optional[Dict]:
        pid = str(patch_id or "").strip()
        if not pid:
            return None
        for row in reversed(self.policy_patch_queue):
            if not isinstance(row, dict):
                continue
            if str(row.get("patch_id") or "").strip() == pid:
                return row
        return None

    def set_policy_patch_candidate_status(
        self,
        *,
        patch_id: str,
        status: str,
        reviewer: str,
        reason: str = "",
    ) -> Optional[Dict]:
        pid = str(patch_id or "").strip()
        st = str(status or "").strip().lower()
        if st not in {"pending", "approved_for_apply", "rejected", "applied_manual"}:
            return None
        import time
        for row in self.policy_patch_queue:
            if not isinstance(row, dict):
                continue
            if str(row.get("patch_id") or "").strip() != pid:
                continue
            row["status"] = st
            row["reviewed_at"] = float(time.time())
            row["reviewed_by"] = str(reviewer or "user")
            row["apply_ready"] = bool(st == "approved_for_apply")
            if reason:
                row["review_reason"] = str(reason)
            self._save()
            return row
        return None

    def get_runtime_overrides_for_user(self, user_id: str) -> Dict[str, Dict]:
        users = self.policy_runtime_overrides.get("users") if isinstance(self.policy_runtime_overrides, dict) else {}
        if not isinstance(users, dict):
            return {}
        raw = users.get(str(user_id or ""))
        return raw if isinstance(raw, dict) else {}

    def list_applied_policy_patches(
        self,
        *,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict]:
        rows = self.policy_applied if isinstance(self.policy_applied, list) else []
        out: List[Dict] = []
        uid = str(user_id or "").strip()
        st = str(status or "").strip().lower()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            if uid and str(row.get("user_id") or "").strip() != uid:
                continue
            if st and str(row.get("status") or "").strip().lower() != st:
                continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def get_applied_policy_patch(self, applied_id: str) -> Optional[Dict]:
        aid = str(applied_id or "").strip()
        if not aid:
            return None
        for row in reversed(self.policy_applied):
            if not isinstance(row, dict):
                continue
            if str(row.get("applied_id") or "").strip() == aid:
                return row
        return None

    def apply_policy_patch_candidate(
        self,
        *,
        patch_id: str,
        applied_by: str,
        reason: str = "",
        require_status: str = "approved_for_apply",
        canary_enabled: bool = False,
        canary_required_observations: int = 3,
        canary_max_failure_rate: float = 0.34,
    ) -> Dict:
        import time
        import uuid

        patch = self.get_policy_patch_candidate(patch_id)
        if not patch:
            return {"ok": False, "error": "Patch candidate not found."}
        current_status = str(patch.get("status") or "").strip().lower()
        if current_status != str(require_status or "approved_for_apply").strip().lower():
            return {"ok": False, "error": f"Patch candidate must be in status '{require_status}'."}

        user_id = str(patch.get("user_id") or "").strip()
        target = str(patch.get("target") or "").strip()
        proposal = patch.get("proposal") if isinstance(patch.get("proposal"), dict) else {}
        if not user_id or not target:
            return {"ok": False, "error": "Patch candidate missing user_id/target."}

        users = self.policy_runtime_overrides.setdefault("users", {})
        user_overrides = users.setdefault(user_id, {})
        previous = user_overrides.get(target)

        applied = {
            "applied_id": f"pap_{uuid.uuid4().hex[:10]}",
            "created_at": float(time.time()),
            "status": "active_canary" if canary_enabled else "active",
            "mode": "manual_apply_guarded_canary" if canary_enabled else "manual_apply_guarded",
            "source_patch_id": str(patch.get("patch_id") or ""),
            "source_suggestion_id": str(patch.get("source_suggestion_id") or ""),
            "user_id": user_id,
            "target": target,
            "proposal": proposal,
            "previous_override": previous,
            "policy_version": patch.get("policy_version"),
            "preference_version": patch.get("preference_version"),
            "applied_by": str(applied_by or "user"),
            "apply_reason": str(reason or ""),
            "canary": {
                "enabled": bool(canary_enabled),
                "required_observations": max(1, int(canary_required_observations)),
                "max_failure_rate": max(0.0, min(1.0, float(canary_max_failure_rate))),
                "promoted_to_active": False,
            },
            "health": {
                "observations": 0,
                "successes": 0,
                "failures": 0,
                "auto_rollback_triggered": False,
            },
        }
        self.policy_applied.append(applied)
        user_overrides[target] = {
            "applied_id": applied["applied_id"],
            "proposal": proposal,
            "updated_at": applied["created_at"],
        }
        patch["status"] = "applied_manual"
        patch["applied_at"] = applied["created_at"]
        patch["applied_by"] = str(applied_by or "user")
        if reason:
            patch["apply_reason"] = str(reason)
        self._save()
        return {"ok": True, "applied_patch": applied}

    def rollback_applied_policy_patch(
        self,
        *,
        applied_id: str,
        reviewer: str,
        reason: str = "",
        automatic: bool = False,
    ) -> Dict:
        import time
        row = self.get_applied_policy_patch(applied_id)
        if not row:
            return {"ok": False, "error": "Applied patch not found."}
        if str(row.get("status") or "").strip().lower() not in {"active", "active_canary"}:
            return {"ok": False, "error": "Applied patch is not active."}

        user_id = str(row.get("user_id") or "").strip()
        target = str(row.get("target") or "").strip()
        previous = row.get("previous_override")

        users = self.policy_runtime_overrides.setdefault("users", {})
        user_overrides = users.setdefault(user_id, {})
        current = user_overrides.get(target)
        if isinstance(current, dict) and str(current.get("applied_id") or "").strip() == str(applied_id):
            if isinstance(previous, dict):
                user_overrides[target] = previous
            else:
                user_overrides.pop(target, None)

        row["status"] = "rolled_back"
        row["rolled_back_at"] = float(time.time())
        row["rolled_back_by"] = str(reviewer or "system")
        row["rollback_reason"] = str(reason or "")
        row["automatic_rollback"] = bool(automatic)
        health = row.get("health") if isinstance(row.get("health"), dict) else {}
        if automatic:
            health["auto_rollback_triggered"] = True
        row["health"] = health
        self._save()
        return {"ok": True, "applied_patch": row}

    def _promote_canary_patch(self, patch: Dict):
        if not isinstance(patch, dict):
            return
        if str(patch.get("status") or "").strip().lower() != "active_canary":
            return
        patch["status"] = "active"
        canary = patch.get("canary") if isinstance(patch.get("canary"), dict) else {}
        canary["promoted_to_active"] = True
        canary["promoted_at"] = __import__("time").time()
        patch["canary"] = canary

    def record_patch_delivery_outcome(self, *, user_id: str, signal_name: str) -> Optional[Dict]:
        name = str(signal_name or "").strip().lower()
        if name not in {"delivery_success", "delivery_failure"}:
            return None
        active = [
            p for p in self.policy_applied
            if isinstance(p, dict)
            and str(p.get("user_id") or "").strip() == str(user_id or "").strip()
            and str(p.get("status") or "").strip().lower() in {"active", "active_canary"}
        ]
        if not active:
            return None

        # Evaluate most recent active patch first.
        patch = sorted(active, key=lambda p: float(p.get("created_at") or 0.0), reverse=True)[0]
        health = patch.get("health") if isinstance(patch.get("health"), dict) else {}
        health["observations"] = int(health.get("observations") or 0) + 1
        if name == "delivery_success":
            health["successes"] = int(health.get("successes") or 0) + 1
        else:
            health["failures"] = int(health.get("failures") or 0) + 1
        patch["health"] = health

        observations = int(health.get("observations") or 0)
        failures = int(health.get("failures") or 0)
        successes = int(health.get("successes") or 0)
        patch_status = str(patch.get("status") or "").strip().lower()
        canary = patch.get("canary") if isinstance(patch.get("canary"), dict) else {}
        canary_enabled = bool(canary.get("enabled")) and patch_status == "active_canary"
        required_obs = max(1, int(canary.get("required_observations") or 3))
        max_failure_rate = max(0.0, min(1.0, float(canary.get("max_failure_rate") or 0.34)))

        should_promote_canary = False
        # Conservative automatic rollback:
        # - during canary, rollback when window reached and failure rate above threshold
        # - outside canary, rollback with repeated failures and no success.
        if canary_enabled:
            if observations >= required_obs:
                failure_rate = float(failures / max(1, observations))
                should_auto_rollback = failure_rate > max_failure_rate
                should_promote_canary = not should_auto_rollback
            else:
                should_auto_rollback = False
        else:
            should_auto_rollback = observations >= 3 and failures >= 3 and successes == 0
        self._save()
        if should_auto_rollback:
            return self.rollback_applied_policy_patch(
                applied_id=str(patch.get("applied_id") or ""),
                reviewer="auto_monitor",
                reason="Automatic rollback: repeated delivery failures after patch apply.",
                automatic=True,
            )
        if should_promote_canary:
            self._promote_canary_patch(patch)
            self._save()
            return {"ok": True, "applied_patch": patch}
        return {"ok": True, "applied_patch": patch}
