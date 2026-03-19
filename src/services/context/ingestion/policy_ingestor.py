from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Tuple

from ..models import RAGChunk, RAGChunkMetadata
from ..vector_store import ContextVectorStore
from .document_chunker import DocumentChunker


class PolicyIngestor:
    collection_name = "policies"

    def __init__(
        self,
        *,
        vector_store: ContextVectorStore,
        repo_root: str | None = None,
        manifest_path: str | None = None,
        chunker: DocumentChunker | None = None,
    ):
        self.repo_root = repo_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        self.vector_store = vector_store
        self.chunker = chunker or DocumentChunker(chunk_size=780, overlap=90)
        self.manifest_path = manifest_path or os.path.join(self.vector_store.base_dir, "manifests", "policies.json")
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)

    def ingest_if_needed(self, force: bool = False) -> Dict[str, int | bool]:
        signature, source_files = self._compute_signature()
        current = self._read_manifest()
        if not force and current.get("signature") == signature:
            return {"ingested": False, "chunks": int(current.get("chunk_count", 0))}
        chunks = self._build_chunks(source_files)
        count = self.vector_store.replace_collection(self.collection_name, chunks)
        self._write_manifest(signature=signature, chunk_count=count, source_count=len(source_files))
        return {"ingested": True, "chunks": count}

    def _compute_signature(self) -> Tuple[str, List[str]]:
        source_files = sorted(self._iter_sources())
        digest = hashlib.sha1()
        for path in source_files:
            digest.update(path.encode("utf-8"))
            digest.update(str(os.path.getmtime(path)).encode("utf-8"))
        return digest.hexdigest(), source_files

    def _iter_sources(self) -> Iterable[str]:
        for rel in (
            ("docs", "worker_task_contract.md"),
            ("docs", "permission_groups_planner.md"),
            ("docs", "driver_ioc_restructure_approval.md"),
            ("docs", "skill_contract.md"),
        ):
            path = os.path.join(self.repo_root, *rel)
            if os.path.exists(path):
                yield path

    def _build_chunks(self, source_files: List[str]) -> List[RAGChunk]:
        chunks: List[RAGChunk] = []
        for path in source_files:
            chunks.extend(self._chunks_from_markdown(path))
        return chunks

    def _chunks_from_markdown(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        sections = self._split_markdown_sections(raw)
        chunks: List[RAGChunk] = []
        source_type = self._classify_source(path)
        updated_at = self._iso_from_mtime(path)
        for index, (section_title, body) in enumerate(sections):
            if not self._looks_like_policy(section_title, body):
                continue
            policy_id = self._slugify(f"{os.path.basename(path)}-{section_title}")
            rule_group = self._infer_rule_group(section_title, body)
            scope_hint = self._infer_scope_hint(section_title, body)
            metadata = RAGChunkMetadata(
                doc_type="policy_section",
                collection_type=self.collection_name,
                source_file=path,
                source_type=source_type,
                created_at=self._iso_now(),
                updated_at=updated_at,
                trust_level="high",
                embedding_version=self.vector_store.embedding_version,
                title=section_title,
                section=section_title,
                tags=self._infer_tags(section_title, body),
                policy_id=policy_id,
                policy_visibility="planner",
                rule_group=rule_group,
                scope_hint=scope_hint,
            )
            chunks.extend(self._make_chunks(text=self._normalize_text(f"{section_title}\n{body}"), metadata=metadata, index=index))
        return chunks

    def _make_chunks(self, *, text: str, metadata: RAGChunkMetadata, index: int) -> List[RAGChunk]:
        parts = self.chunker.chunk(text)
        chunks: List[RAGChunk] = []
        for chunk_index, part in enumerate(parts):
            meta = RAGChunkMetadata(**{**asdict(metadata), "chunk_index": chunk_index, "total_chunks": len(parts)})
            chunk_id = hashlib.sha1(
                f"{self.collection_name}|{metadata.source_file}|{metadata.policy_id}|{index}|{chunk_index}".encode("utf-8")
            ).hexdigest()
            chunks.append(RAGChunk(chunk_id=chunk_id, content=part, metadata=meta))
        return chunks

    @staticmethod
    def _split_markdown_sections(raw: str) -> List[Tuple[str, str]]:
        sections: List[Tuple[str, List[str]]] = []
        current_title = "Document Overview"
        current_lines: List[str] = []
        for line in raw.splitlines():
            match = re.match(r"^(#{1,6})\s+(.*)$", line)
            if match:
                if current_lines:
                    sections.append((current_title, current_lines))
                current_title = match.group(2).strip() or "Untitled Section"
                current_lines = []
                continue
            current_lines.append(line)
        if current_lines:
            sections.append((current_title, current_lines))
        return [(title, "\n".join(lines).strip()) for title, lines in sections if "\n".join(lines).strip()]

    @staticmethod
    def _looks_like_policy(title: str, body: str) -> bool:
        haystack = f"{title}\n{body}".lower()
        markers = (
            "must",
            "must not",
            "required",
            "approval",
            "permission",
            "policy",
            "contract",
            "rule",
            "rules",
            "access",
            "fallback",
            "authorization",
            "compliance",
            "allowed",
            "forbidden",
            "deve",
            "obrigat",
            "permiss",
            "aprova",
            "contrato",
            "regra",
            "regras",
        )
        return any(marker in haystack for marker in markers)

    @staticmethod
    def _normalize_text(text: str) -> str:
        clean = re.sub(r"```.*?```", lambda m: " ".join(m.group(0).split()), text, flags=re.DOTALL)
        return " ".join(clean.split())

    @staticmethod
    def _classify_source(path: str) -> str:
        normalized = path.replace("\\", "/")
        if normalized.endswith("worker_task_contract.md"):
            return "worker_contract"
        if normalized.endswith("permission_groups_planner.md"):
            return "permission_planner"
        if normalized.endswith("driver_ioc_restructure_approval.md"):
            return "approval_doc"
        if normalized.endswith("skill_contract.md"):
            return "skill_contract"
        return "policy_doc"

    @staticmethod
    def _infer_rule_group(title: str, body: str) -> str:
        haystack = f"{title} {body}".lower()
        if "approval" in haystack or "aprova" in haystack:
            return "approval"
        if "permission" in haystack or "access" in haystack or "permiss" in haystack:
            return "access_control"
        if "fallback" in haystack:
            return "fallback"
        if "contract" in haystack:
            return "contract"
        return "governance"

    @staticmethod
    def _infer_scope_hint(title: str, body: str) -> str:
        haystack = f"{title} {body}".lower()
        if "worker" in haystack:
            return "worker"
        if "provider" in haystack:
            return "provider"
        if "interface" in haystack or "driver" in haystack:
            return "interface"
        if "user" in haystack or "chat" in haystack:
            return "principal"
        return "system"

    @staticmethod
    def _infer_tags(title: str, body: str) -> str:
        haystack = f"{title} {body}".lower()
        tags = []
        for tag in ("approval", "permission", "access", "worker", "contract", "fallback", "provider", "safety"):
            if tag in haystack:
                tags.append(tag)
        return ",".join(tags)

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
        return slug or "policy"

    def _read_manifest(self) -> Dict[str, object]:
        if not os.path.exists(self.manifest_path):
            return {}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {}

    def _write_manifest(self, *, signature: str, chunk_count: int, source_count: int) -> None:
        with open(self.manifest_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "signature": signature,
                    "chunk_count": int(chunk_count),
                    "source_count": int(source_count),
                    "updated_at": self._iso_now(),
                },
                handle,
                indent=2,
                ensure_ascii=False,
            )

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _iso_from_mtime(path: str) -> str:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
