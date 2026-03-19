from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ..models import RAGChunk, RAGChunkMetadata
from ..vector_store import ContextVectorStore
from .document_chunker import DocumentChunker


class ExampleIngestor:
    collection_name = "examples"

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
        self.chunker = chunker or DocumentChunker(chunk_size=700, overlap=80)
        self.manifest_path = manifest_path or os.path.join(self.vector_store.base_dir, "manifests", "examples.json")
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
        source_files: List[str] = []
        for root, _, files in os.walk(os.path.join(self.repo_root, "src", "capabilities")):
            for filename in files:
                if filename in {"contract.json", "README.md", "example_flow.py"}:
                    source_files.append(os.path.join(root, filename))
        source_files.sort()
        digest = hashlib.sha1()
        for path in source_files:
            digest.update(path.encode("utf-8"))
            digest.update(str(os.path.getmtime(path)).encode("utf-8"))
        return digest.hexdigest(), source_files

    def _build_chunks(self, source_files: List[str]) -> List[RAGChunk]:
        chunks: List[RAGChunk] = []
        for path in source_files:
            if path.endswith("contract.json"):
                chunks.extend(self._chunks_from_contract(path))
            elif path.endswith("README.md"):
                chunks.extend(self._chunks_from_readme(path))
            elif path.endswith("example_flow.py"):
                chunks.extend(self._chunks_from_example_flow(path))
        return chunks

    def _chunks_from_contract(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        capability = payload.get("capability") if isinstance(payload.get("capability"), dict) else {}
        capability_id = str(capability.get("id") or os.path.basename(os.path.dirname(path)))
        updated_at = self._iso_from_mtime(path)
        chunks: List[RAGChunk] = []
        for action in payload.get("actions") or []:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or "").strip()
            for example_index, example in enumerate(action.get("examples") or [], start=1):
                if not isinstance(example, dict):
                    continue
                example_payload = json.dumps(example, ensure_ascii=False, separators=(",", ":"))
                title = f"{action_id} example {example_index}"
                metadata = RAGChunkMetadata(
                    doc_type="action_example",
                    collection_type=self.collection_name,
                    source_file=path,
                    source_type="contract_example",
                    capability_id=capability_id,
                    action_id=action_id,
                    created_at=self._iso_now(),
                    updated_at=updated_at,
                    trust_level="high",
                    embedding_version=self.vector_store.embedding_version,
                    title=title,
                    example_type="contract_action_example",
                    tags="usage,contract",
                    success_signal="valid_action_usage",
                )
                chunk_id = hashlib.sha1(
                    f"{self.collection_name}|{path}|{action_id}|contract|{example_index}".encode("utf-8")
                ).hexdigest()
                content = f"Example usage for {action_id}. capability: {capability_id}. example: {example_payload}"
                chunks.append(RAGChunk(chunk_id=chunk_id, content=content, metadata=metadata))
        return chunks

    def _chunks_from_readme(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        capability_id = os.path.basename(os.path.dirname(path))
        updated_at = self._iso_from_mtime(path)
        chunks: List[RAGChunk] = []
        for index, (label, block) in enumerate(self._extract_readme_examples(raw), start=1):
            metadata = RAGChunkMetadata(
                doc_type="readme_example",
                collection_type=self.collection_name,
                source_file=path,
                source_type="readme_example",
                capability_id=capability_id,
                created_at=self._iso_now(),
                updated_at=updated_at,
                trust_level="medium",
                embedding_version=self.vector_store.embedding_version,
                title=f"{capability_id} {label}",
                example_type="readme_usage_example",
                section=label,
                tags="usage,readme",
                success_signal="illustrative_usage",
            )
            chunk_id = hashlib.sha1(f"{self.collection_name}|{path}|readme|{label}|{index}".encode("utf-8")).hexdigest()
            chunks.append(RAGChunk(chunk_id=chunk_id, content=self._normalize_text(block), metadata=metadata))
        return chunks

    def _chunks_from_example_flow(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        capability_id = os.path.basename(os.path.dirname(path))
        updated_at = self._iso_from_mtime(path)
        title = f"{capability_id} example flow"
        metadata = RAGChunkMetadata(
            doc_type="example_flow",
            collection_type=self.collection_name,
            source_file=path,
            source_type="python_example_flow",
            capability_id=capability_id,
            created_at=self._iso_now(),
            updated_at=updated_at,
            trust_level="medium",
            embedding_version=self.vector_store.embedding_version,
            title=title,
            example_type="flow_script",
            tags="flow,python,usage",
            success_signal="successful_flow_demo",
        )
        parts = self.chunker.chunk(self._normalize_python_example(raw))
        chunks: List[RAGChunk] = []
        for index, part in enumerate(parts):
            meta = RAGChunkMetadata(**{**asdict(metadata), "chunk_index": index, "total_chunks": len(parts)})
            chunk_id = hashlib.sha1(f"{self.collection_name}|{path}|flow|{index}".encode("utf-8")).hexdigest()
            chunks.append(RAGChunk(chunk_id=chunk_id, content=part, metadata=meta))
        return chunks

    @staticmethod
    def _extract_readme_examples(raw: str) -> List[Tuple[str, str]]:
        matches: List[Tuple[str, str]] = []
        fenced_blocks = re.findall(r"```(?:json|python)?\n(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        if "usage example" in raw.lower():
            for index, block in enumerate(fenced_blocks, start=1):
                matches.append((f"usage example {index}", block))
        return matches

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").split())

    @staticmethod
    def _normalize_python_example(raw: str) -> str:
        lines = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("print(") or stripped.startswith("async def") or "runtime." in stripped or "subagent" in stripped:
                lines.append(stripped)
        return " ".join(lines)[:2200]

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
