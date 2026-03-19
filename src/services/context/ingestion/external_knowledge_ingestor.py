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


class ExternalKnowledgeIngestor:
    collection_name = "external_knowledge"

    def __init__(
        self,
        *,
        vector_store: ContextVectorStore,
        repo_root: str | None = None,
        knowledge_dir: str | None = None,
        manifest_path: str | None = None,
        chunker: DocumentChunker | None = None,
    ):
        self.repo_root = repo_root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        self.vector_store = vector_store
        self.knowledge_dir = knowledge_dir or os.path.join(self.repo_root, "data", "knowledge", "external")
        os.makedirs(self.knowledge_dir, exist_ok=True)
        self.chunker = chunker or DocumentChunker(chunk_size=780, overlap=90)
        self.manifest_path = manifest_path or os.path.join(self.vector_store.base_dir, "manifests", "external_knowledge.json")
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
        manifest = self._metadata_manifest()
        digest.update(json.dumps(manifest, sort_keys=True).encode("utf-8"))
        for path in source_files:
            digest.update(path.encode("utf-8"))
            digest.update(str(os.path.getmtime(path)).encode("utf-8"))
        return digest.hexdigest(), source_files

    def _iter_sources(self) -> Iterable[str]:
        docs_dir = os.path.join(self.repo_root, "docs")
        if os.path.isdir(docs_dir):
            for name in sorted(os.listdir(docs_dir)):
                path = os.path.join(docs_dir, name)
                if os.path.isfile(path) and name.lower().endswith(".md"):
                    yield path
        readme = os.path.join(self.repo_root, "README.md")
        if os.path.exists(readme):
            yield readme
        for root, _, files in os.walk(self.knowledge_dir):
            for name in sorted(files):
                if name.startswith("_manifest"):
                    continue
                if not name.lower().endswith((".md", ".txt")):
                    continue
                yield os.path.join(root, name)

    def _build_chunks(self, source_files: List[str]) -> List[RAGChunk]:
        manifest = self._metadata_manifest()
        chunks: List[RAGChunk] = []
        for path in source_files:
            overrides = manifest.get(self._manifest_key(path), {})
            chunks.extend(self._chunks_from_file(path, overrides))
        return chunks

    def _chunks_from_file(self, path: str, overrides: Dict[str, object]) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        sections = self._split_sections(raw)
        source_type = self._classify_source(path)
        updated_at = self._iso_from_mtime(path)
        default_visibility = str(overrides.get("policy_visibility") or ("public" if source_type == "repo_docs" else "internal"))
        default_scope = str(overrides.get("knowledge_scope") or ("global" if source_type == "repo_docs" else "workspace"))
        default_trust = str(overrides.get("trust_level") or ("curated" if source_type == "repo_docs" else "imported"))
        origin = str(overrides.get("origin") or source_type)
        tags = str(overrides.get("tags") or "")
        author = str(overrides.get("author") or "")
        version = str(overrides.get("version") or "")
        principal_id = str(overrides.get("principal_id") or "")
        tenant_id = str(overrides.get("tenant_id") or "")

        chunks: List[RAGChunk] = []
        for section_index, (title, body) in enumerate(sections):
            normalized = self._normalize_text(f"{title}\n{body}")
            if len(normalized) < 40:
                continue
            metadata = RAGChunkMetadata(
                doc_type="external_knowledge",
                collection_type=self.collection_name,
                source_file=path,
                source_type=source_type,
                created_at=self._iso_now(),
                updated_at=updated_at,
                embedding_version=self.vector_store.embedding_version,
                trust_level=default_trust,
                policy_visibility=default_visibility,
                knowledge_scope=default_scope,
                principal_id=principal_id,
                tenant_id=tenant_id,
                title=title,
                section=title,
                tags=tags or self._infer_tags(title, body),
                origin=origin,
                author=author,
                version=version,
            )
            chunks.extend(self._make_chunks(text=normalized, metadata=metadata, index=section_index))
        return chunks

    def _make_chunks(self, *, text: str, metadata: RAGChunkMetadata, index: int) -> List[RAGChunk]:
        parts = self.chunker.chunk(text)
        rows: List[RAGChunk] = []
        for chunk_index, part in enumerate(parts):
            meta = RAGChunkMetadata(**{**asdict(metadata), "chunk_index": chunk_index, "total_chunks": len(parts)})
            chunk_id = hashlib.sha1(
                f"{self.collection_name}|{metadata.source_file}|{metadata.section}|{index}|{chunk_index}".encode("utf-8")
            ).hexdigest()
            rows.append(RAGChunk(chunk_id=chunk_id, content=part, metadata=meta))
        return rows

    @staticmethod
    def _split_sections(raw: str) -> List[Tuple[str, str]]:
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
    def _normalize_text(text: str) -> str:
        clean = re.sub(r"```.*?```", lambda m: " ".join(m.group(0).split()), text, flags=re.DOTALL)
        return " ".join(clean.split())

    def _metadata_manifest(self) -> Dict[str, Dict[str, object]]:
        manifest_file = os.path.join(self.knowledge_dir, "_manifest.json")
        if not os.path.exists(manifest_file):
            return {}
        try:
            with open(manifest_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return {}
        entries = payload.get("files") if isinstance(payload, dict) else {}
        return entries if isinstance(entries, dict) else {}

    def _manifest_key(self, path: str) -> str:
        if path.startswith(self.knowledge_dir):
            return os.path.relpath(path, self.knowledge_dir).replace("\\", "/")
        return os.path.relpath(path, self.repo_root).replace("\\", "/")

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

    def _classify_source(self, path: str) -> str:
        normalized = path.replace("\\", "/")
        if normalized.startswith(self.knowledge_dir.replace("\\", "/")):
            return "external_drop"
        if normalized.endswith("README.md"):
            return "repo_readme"
        return "repo_docs"

    @staticmethod
    def _infer_tags(title: str, body: str) -> str:
        haystack = f"{title} {body}".lower()
        tags = []
        for tag in ("guide", "workflow", "reference", "integration", "browser", "policy", "contract", "api"):
            if tag in haystack:
                tags.append(tag)
        return ",".join(tags)

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _iso_from_mtime(path: str) -> str:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
