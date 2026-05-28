from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.memory.episodic_memory import EpisodicMemoryService

from ..models import RAGChunk, RAGChunkMetadata
from ..vector_store import ContextVectorStore


@dataclass(slots=True)
class ExperienceCandidate:
    title: str
    content: str
    metadata: RAGChunkMetadata


class AgentExperienceIngestor:
    collection_name = "agent_experience"

    _FAILURE_MARKERS = (
        "fail",
        "failed",
        "failure",
        "error",
        "timeout",
        "denied",
        "permission",
        "approval",
        "retry",
        "fallback",
        "replan",
        "recover",
        "stalled",
        "missing",
        "unavailable",
        "exception",
        "blocked",
        "auth",
        "restart",
    )
    _NOISE_MARKERS = (
        "called action",
        "user asked",
        "execution status success",
        "ok",
        "done",
        "success",
        "completed",
    )
    _NEGATED_FAILURE_MARKERS = (
        "no failure",
        "no failures",
        "without failure",
        "not failed",
        "not fail",
        "no error",
        "no errors",
        "without error",
        "without errors",
    )
    _POSITIVE_TRACE_TYPES = (
        "completed",
        "success",
        "done",
        "ok",
        "success_path",
        "task_completed",
        "action_executed",
        "turn_complete",
    )
    _ERROR_TYPE_RULES = (
        (("permission", "denied", "approval"), "permission_denied"),
        (("timeout", "stalled"), "timeout"),
        (("auth", "credential", "api key"), "configuration"),
        (("path", "not found"), "path_resolution"),
        (("path", "normalize"), "path_resolution"),
        (("missing",), "missing_input"),
    )
    _RECOVERY_TYPE_RULES = (
        (("restart",), "restart"),
        (("fallback",), "fallback"),
        (("replan",), "replan"),
        (("approval", "configuration guidance"), "escalate_guidance"),
        (("retry",), "retry"),
    )
    _ENVIRONMENT_HINT_RULES = (
        (("browser",), "browser_runtime"),
        (("shell", "path"), "shell_runtime"),
        (("api key", "credential", "config"), "configured_capability"),
        (("permission", "approval"), "governance"),
    )
    _TAG_RULES = (
        "retry",
        "fallback",
        "replan",
        "approval",
        "permission",
        "browser",
        "shell",
        "config",
        "timeout",
        "path",
    )

    def __init__(
        self,
        *,
        vector_store: ContextVectorStore,
        episodic_memory_service: EpisodicMemoryService | None = None,
    ):
        self.vector_store = vector_store
        self.episodic_memory_service = episodic_memory_service
        self.last_stats: Dict[str, int] = {}

    def promote_session_experience(self, session) -> Dict[str, int]:
        stats = {
            "evaluated": 0,
            "accepted": 0,
            "suppressed_noise": 0,
            "suppressed_duplicates": 0,
        }
        accepted: List[ExperienceCandidate] = []
        normalized_texts: List[str] = []
        semantic_signatures: List[str] = []

        for raw in self._iter_raw_records(session):
            stats["evaluated"] += 1
            candidate = self._candidate_from_raw(raw=raw, session=session)
            if candidate is None:
                stats["suppressed_noise"] += 1
                continue
            normalized = self._normalize_for_dedupe(candidate.content)
            signature = self._semantic_signature(candidate)
            if signature and signature in semantic_signatures:
                stats["suppressed_duplicates"] += 1
                continue
            if self._is_duplicate(normalized, normalized_texts):
                stats["suppressed_duplicates"] += 1
                continue
            if self._matches_existing(candidate):
                stats["suppressed_duplicates"] += 1
                continue
            normalized_texts.append(normalized)
            if signature:
                semantic_signatures.append(signature)
            accepted.append(candidate)

        chunks = [self._chunk_from_candidate(candidate) for candidate in accepted]
        count = self.vector_store.upsert_documents(self.collection_name, chunks)
        stats["accepted"] = count
        self.last_stats = stats
        return dict(stats)

    def _iter_raw_records(self, session) -> Iterable[Dict[str, Any]]:
        for trace in getattr(session, "decision_traces", None) or []:
            yield {"source_type": "decision_trace", "payload": trace}
        for event in getattr(session, "event_history", None) or []:
            yield {"source_type": "event_history", "payload": event}
        for task_id, task in (getattr(session, "task_registry", None) or {}).items():
            yield {"source_type": "task_registry", "task_id": task_id, "payload": task}
        for episode in self._iter_episodic_rows():
            yield {"source_type": "episodic_memory", "payload": episode}

    def _iter_episodic_rows(self) -> Iterable[Dict[str, Any]]:
        service = self.episodic_memory_service
        if service is None or getattr(service, "collection", None) is None:
            return []
        try:
            rows = service.collection.get(include=["documents", "metadatas"])
        except Exception:
            return []
        documents = rows.get("documents") or []
        metadatas = rows.get("metadatas") or []
        ids = rows.get("ids") or []
        items: List[Dict[str, Any]] = []
        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) else {}
            row_id = ids[index] if index < len(ids) else ""
            items.append({"id": row_id, "document": document, "metadata": metadata or {}})
        return items[-20:]

    def _candidate_from_raw(self, *, raw: Dict[str, Any], session) -> ExperienceCandidate | None:
        source_type = str(raw.get("source_type") or "").strip()
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        if source_type == "decision_trace":
            return self._from_decision_trace(payload=payload, session=session)
        if source_type == "event_history":
            return self._from_event(payload=payload, session=session)
        if source_type == "task_registry":
            return self._from_task(task_id=str(raw.get("task_id") or ""), payload=payload, session=session)
        if source_type == "episodic_memory":
            return self._from_episode(payload=payload, session=session)
        return None

    def _from_decision_trace(self, *, payload: Dict[str, Any], session) -> ExperienceCandidate | None:
        assessment = payload.get("recovery_assessment") if isinstance(payload.get("recovery_assessment"), dict) else {}
        event_type = str(payload.get("event_type") or payload.get("decision_type") or "").strip()
        selected_outcome = str(payload.get("selected_outcome") or "").strip().lower()
        reason = str(assessment.get("reason") or "").strip()
        recommendation = str(assessment.get("recommendation") or payload.get("selected_outcome") or "").strip()
        error_type = str(assessment.get("error_code") or "").strip()
        task_role = str(payload.get("task_role") or payload.get("task_id") or "operation").strip()
        if event_type.lower() in self._POSITIVE_TRACE_TYPES or selected_outcome in self._POSITIVE_TRACE_TYPES:
            return None
        if not self._has_future_value(" ".join((event_type, reason, recommendation, error_type, task_role))):
            return None
        condition = self._summarize_condition(reason or event_type or error_type)
        action = self._summarize_recovery(recommendation=recommendation, reason=reason, task_role=task_role)
        if not action:
            return None
        text = f"When {condition}, {action}."
        return self._build_candidate(
            title=f"Recovery pattern for {task_role}",
            content=text,
            session=session,
            source_type="decision_trace",
            capability_id=self._capability_from_action(task_role),
            action_id=task_role if "." in task_role else "",
            status=str(payload.get("selected_outcome") or "").strip().lower() or "recovery",
            experience_type="recovery_pattern",
            success_signal="recovered" if recommendation.upper() in {"RETRY", "FALLBACK", "REPLAN"} else "advisory",
            environment_hint=self._environment_hint(reason),
            error_type=error_type or self._infer_error_type(reason),
            recovery_type=recommendation.lower(),
            created_at=str(payload.get("timestamp") or self._iso_now()),
            updated_at=str(payload.get("timestamp") or self._iso_now()),
            source_file=f"session:{getattr(session, 'session_id', 'unknown')}:decision_traces",
            tags=self._infer_tags(text),
        )

    def _from_event(self, *, payload: Dict[str, Any], session) -> ExperienceCandidate | None:
        event_type = str(payload.get("event_type") or "").strip().upper()
        if event_type not in {"FAILED", "RECOVERY_NEEDED", "STALLED"}:
            return None
        summary = str(payload.get("failure_summary") or payload.get("summary") or "").strip()
        task_role = str(payload.get("task_role") or payload.get("task_id") or "operation").strip()
        error_code = str(payload.get("error_code") or "").strip()
        if not self._has_future_value(" ".join((event_type, summary, error_code, task_role))):
            return None
        recovery = self._heuristic_event_recovery(summary=summary, error_code=error_code, task_role=task_role)
        if not recovery:
            return None
        text = f"When {self._summarize_condition(summary or error_code or event_type)}, {recovery}."
        return self._build_candidate(
            title=f"Failure handling for {task_role}",
            content=text,
            session=session,
            source_type="event_history",
            capability_id=self._capability_from_action(task_role),
            action_id=task_role if "." in task_role else "",
            status=event_type.lower(),
            experience_type="failure_pattern",
            success_signal="advisory",
            environment_hint=self._environment_hint(summary),
            error_type=error_code or self._infer_error_type(summary),
            recovery_type=self._infer_recovery_type(recovery),
            created_at=str(payload.get("timestamp") or self._iso_now()),
            updated_at=str(payload.get("timestamp") or self._iso_now()),
            source_file=f"session:{getattr(session, 'session_id', 'unknown')}:event_history",
            tags=self._infer_tags(text),
        )

    def _from_task(self, *, task_id: str, payload: Dict[str, Any], session) -> ExperienceCandidate | None:
        failure_summary = str(payload.get("last_failure_summary") or "").strip()
        task_role = str(payload.get("task_role") or task_id or "operation").strip()
        retries = int(payload.get("retry_count") or 0)
        fallback_action = str(payload.get("next_fallback_action") or "").strip()
        if retries < 2 and not fallback_action:
            return None
        if not self._has_future_value(" ".join((failure_summary, fallback_action, task_role))):
            return None
        if fallback_action:
            recovery = f"prefer fallback via {fallback_action} instead of repeated retries"
            recovery_type = "fallback"
        else:
            recovery = "switch to replanning or operator guidance instead of retrying the same path"
            recovery_type = "replan"
        text = f"When {self._summarize_condition(failure_summary or task_role)}, {recovery}."
        return self._build_candidate(
            title=f"Escalation lesson for {task_role}",
            content=text,
            session=session,
            source_type="task_registry",
            capability_id=self._capability_from_action(task_role),
            action_id=task_role if "." in task_role else "",
            status=str(payload.get("status") or "tracked").lower(),
            experience_type="recovery_pattern",
            success_signal="advisory",
            environment_hint=self._environment_hint(failure_summary),
            error_type=self._infer_error_type(failure_summary),
            recovery_type=recovery_type,
            created_at=self._iso_now(),
            updated_at=self._iso_now(),
            source_file=f"session:{getattr(session, 'session_id', 'unknown')}:task_registry",
            tags=self._infer_tags(text),
        )

    def _from_episode(self, *, payload: Dict[str, Any], session) -> ExperienceCandidate | None:
        document = str(payload.get("document") or "").strip()
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        try:
            episode = json.loads(document)
        except Exception:
            return None
        status = str(episode.get("s") or metadata.get("status") or "").strip().lower()
        action = str(episode.get("a") or metadata.get("action") or "operation").strip()
        observation = str(episode.get("o") or "").strip()
        if status == "success":
            return None
        if not self._has_future_value(" ".join((status, action, observation))):
            return None
        recovery = self._heuristic_event_recovery(summary=observation, error_code="", task_role=action)
        if not recovery:
            return None
        text = f"When {self._summarize_condition(observation or action)}, {recovery}."
        ts = metadata.get("timestamp")
        timestamp = self._iso_from_timestamp(ts) if ts else self._iso_now()
        return self._build_candidate(
            title=f"Episodic lesson for {action or 'operation'}",
            content=text,
            session=session,
            source_type="episodic_memory",
            capability_id=self._capability_from_action(action),
            action_id=action if "." in action else "",
            status=status or "failure",
            experience_type="failure_pattern",
            success_signal="advisory",
            environment_hint=self._environment_hint(observation),
            error_type=self._infer_error_type(observation),
            recovery_type=self._infer_recovery_type(recovery),
            created_at=timestamp,
            updated_at=timestamp,
            source_file="episodic_memory",
            tags=self._infer_tags(text),
        )

    def _build_candidate(
        self,
        *,
        title: str,
        content: str,
        session,
        source_type: str,
        capability_id: str,
        action_id: str,
        status: str,
        experience_type: str,
        success_signal: str,
        environment_hint: str,
        error_type: str,
        recovery_type: str,
        created_at: str,
        updated_at: str,
        source_file: str,
        tags: str,
    ) -> ExperienceCandidate | None:
        compact = self._compact(content)
        if not compact or not self._has_future_value(compact):
            return None
        normalized = self._normalize_for_dedupe(compact)
        metadata = RAGChunkMetadata(
            doc_type="agent_experience",
            collection_type=self.collection_name,
            source_file=source_file,
            source_type=source_type,
            created_at=created_at,
            updated_at=updated_at,
            embedding_version=self.vector_store.embedding_version,
            capability_id=capability_id,
            action_id=action_id,
            principal_id="",
            tenant_id="",
            trust_level="medium" if source_type == "episodic_memory" else "high",
            title=title.strip() or "Agent Experience",
            chunk_index=0,
            total_chunks=1,
            status=status,
            experience_type=experience_type,
            success_signal=success_signal,
            environment_hint=environment_hint,
            provenance_hash=hashlib.sha1(normalized.encode("utf-8")).hexdigest(),
            session_id=str(getattr(session, "session_id", "") or ""),
            error_type=error_type,
            recovery_type=recovery_type,
            tags=tags,
        )
        return ExperienceCandidate(title=metadata.title, content=compact, metadata=metadata)

    def _chunk_from_candidate(self, candidate: ExperienceCandidate) -> RAGChunk:
        chunk_id = hashlib.sha1(
            f"{self.collection_name}|{candidate.metadata.provenance_hash}|{candidate.metadata.action_id}|{candidate.metadata.experience_type}".encode("utf-8")
        ).hexdigest()
        return RAGChunk(chunk_id=chunk_id, content=candidate.content, metadata=candidate.metadata)

    def _matches_existing(self, candidate: ExperienceCandidate) -> bool:
        existing = self.vector_store.query(self.collection_name, candidate.content, n_results=3)
        normalized = self._normalize_for_dedupe(candidate.content)
        signature = self._semantic_signature(candidate)
        for row in existing:
            content = str(row.get("content") or "").strip()
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if signature and signature == self._semantic_signature_from_metadata(metadata):
                return True
            if self._is_duplicate(normalized, [self._normalize_for_dedupe(content)]):
                return True
        return False

    @classmethod
    def _is_duplicate(cls, normalized: str, existing_normalized: Sequence[str]) -> bool:
        for other in existing_normalized:
            if normalized == other:
                return True
            if cls._similarity(normalized, other) >= 0.86:
                return True
        return False

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return overlap / union if union else 0.0

    @classmethod
    def _has_future_value(cls, text: str) -> bool:
        clean = cls._normalize_for_dedupe(text)
        if len(clean) < 24:
            return False
        if any(marker in clean for marker in cls._NOISE_MARKERS):
            return False
        if any(marker in clean for marker in cls._NEGATED_FAILURE_MARKERS):
            return False
        if any(marker in clean for marker in cls._FAILURE_MARKERS):
            return True
        if any(marker in clean for marker in ("configure", "approval path", "normalize path", "restart", "retry loop")):
            return True
        return False

    @classmethod
    def _normalize_for_dedupe(cls, text: str) -> str:
        lowered = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())
        tokens = [token for token in lowered.split() if token and token not in {"the", "and", "for", "with", "that", "this", "then"}]
        return " ".join(tokens)

    @classmethod
    def _summarize_condition(cls, text: str) -> str:
        clean = cls._compact(text, limit=120).strip().rstrip(".")
        clean = re.sub(r"^(when|if)\s+", "", clean, flags=re.IGNORECASE)
        if not clean:
            return "an operational failure repeats"
        lowered = clean.lower()
        if lowered.startswith(("browser", "shell", "permission", "approval", "auth", "timeout", "stalled")):
            return clean
        return clean[0].lower() + clean[1:] if len(clean) > 1 else clean.lower()

    @classmethod
    def _summarize_recovery(cls, *, recommendation: str, reason: str, task_role: str) -> str:
        rec = recommendation.strip().upper()
        reason_l = reason.lower()
        for markers, message in (
            (("permission", "approval", "denied"), "surface the approval or configuration path instead of retrying the same action"),
            (("auth", "credential", "api key"), "surface configuration guidance before attempting another execution"),
            (("timeout", "stalled"), f"reduce scope and retry {task_role} once after refreshing runtime state"),
        ):
            if any(marker in reason_l for marker in markers):
                return message
        for marker, message in (
            ("FALLBACK", f"prefer a fallback capability for {task_role} instead of repeating the failing path"),
            ("REPLAN", "replan the task instead of retrying the same failing sequence"),
            ("ESCALATE", "escalate for approval or human review instead of continuing autonomous retries"),
            ("RETRY", f"retry {task_role} only after refreshing environment state"),
        ):
            if rec == marker:
                return message
        return ""

    @classmethod
    def _heuristic_event_recovery(cls, *, summary: str, error_code: str, task_role: str) -> str:
        text = " ".join((summary or "", error_code or "", task_role or "")).lower()
        if not cls._has_future_value(text):
            return ""
        recovery_rules = (
            (("permission", "denied", "approval"), None, "surface the approval path instead of retrying the blocked action"),
            (("auth", "api key", "credential", "config"), None, "surface configuration guidance before attempting another execution"),
            (("browser",), ("stale", "session", "target"), "restart browser control before retrying the extraction sequence"),
            (("path",), ("normalize", "not found"), "normalize the target path before the next retry"),
            (("timeout", "stalled"), None, f"retry {task_role or 'the operation'} once after reducing scope or refreshing state"),
            (("missing", "not found"), None, "validate inputs and environment prerequisites before repeating the action"),
        )
        for required_any, companion_any, message in recovery_rules:
            if any(marker in text for marker in required_any) and (
                companion_any is None or any(marker in text for marker in companion_any)
            ):
                return message
        return ""

    @staticmethod
    def _capability_from_action(action_id: str) -> str:
        action = str(action_id or "").strip()
        return action.split(".", 1)[0] if "." in action else ""

    @classmethod
    def _infer_error_type(cls, text: str) -> str:
        lowered = str(text or "").lower()
        for markers, label in cls._ERROR_TYPE_RULES:
            if all(marker in lowered for marker in markers):
                return label
        return "operational_error"

    @classmethod
    def _infer_recovery_type(cls, text: str) -> str:
        lowered = str(text or "").lower()
        for markers, label in cls._RECOVERY_TYPE_RULES:
            if all(marker in lowered for marker in markers):
                return label
        return "advisory"

    @classmethod
    def _environment_hint(cls, text: str) -> str:
        lowered = str(text or "").lower()
        for markers, label in cls._ENVIRONMENT_HINT_RULES:
            if any(marker in lowered for marker in markers):
                return label
        return "general_runtime"

    @classmethod
    def _infer_tags(cls, text: str) -> str:
        lowered = str(text or "").lower()
        tags = []
        for tag in cls._TAG_RULES:
            if tag in lowered:
                tags.append(tag)
        return ",".join(tags)

    @staticmethod
    def _semantic_signature(candidate: ExperienceCandidate) -> str:
        return AgentExperienceIngestor._semantic_signature_from_metadata(candidate.metadata.to_chroma())

    @staticmethod
    def _semantic_signature_from_metadata(metadata: Dict[str, Any]) -> str:
        parts = [
            str(metadata.get("action_id") or "").strip().lower(),
            str(metadata.get("error_type") or "").strip().lower(),
            str(metadata.get("recovery_type") or "").strip().lower(),
            str(metadata.get("experience_type") or "").strip().lower(),
            str(metadata.get("environment_hint") or "").strip().lower(),
        ]
        compact = "|".join(parts).strip("|")
        return compact

    @staticmethod
    def _compact(text: str, limit: int = 240) -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) <= limit:
            return clean
        return clean[:limit].rstrip() + "..."

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _iso_from_timestamp(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return AgentExperienceIngestor._iso_now()
        return datetime.fromtimestamp(numeric, tz=timezone.utc).isoformat()
