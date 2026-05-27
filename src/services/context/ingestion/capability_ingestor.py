from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ..models import RAGChunk, RAGChunkMetadata
from ..vector_store import ContextVectorStore
from .document_chunker import DocumentChunker


class CapabilityKnowledgeIngestor:
    collection_name = "capability_knowledge"

    def __init__(
        self,
        *,
        vector_store: ContextVectorStore,
        capabilities_dir: str | None = None,
        manifest_path: str | None = None,
        chunker: DocumentChunker | None = None,
    ):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        self.capabilities_dir = capabilities_dir or os.path.join(root_dir, "src", "capabilities")
        self.vector_store = vector_store
        self.chunker = chunker or DocumentChunker()
        self.manifest_path = manifest_path or os.path.join(self.vector_store.base_dir, "manifests", "capability_knowledge.json")
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)

    def ingest_if_needed(self, force: bool = False) -> Dict[str, int | bool]:
        signature, source_files = self._compute_signature()
        current = self._read_manifest()
        if not force and current.get("signature") == signature:
            return {"ingested": False, "chunks": int(current.get("chunk_count", 0))}

        chunks = self._build_chunks(source_files)
        chunk_count = self.vector_store.replace_collection(self.collection_name, chunks)
        self._write_manifest(signature=signature, chunk_count=chunk_count, source_count=len(source_files))
        return {"ingested": True, "chunks": chunk_count}

    def _compute_signature(self) -> Tuple[str, List[str]]:
        source_files: List[str] = []
        for root, _, files in os.walk(self.capabilities_dir):
            for filename in files:
                if filename not in {"contract.json", "README.md", "config.schema.json"}:
                    continue
                path = os.path.join(root, filename)
                source_files.append(path)
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
            elif path.endswith("config.schema.json"):
                chunks.extend(self._chunks_from_schema(path))
        return chunks

    def _chunks_from_contract(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        capability = payload.get("capability") if isinstance(payload.get("capability"), dict) else {}
        capability_id = str(capability.get("id") or self._capability_id_from_path(path))
        created_at = self._iso_now()
        updated_at = self._iso_from_mtime(path)
        chunks: List[RAGChunk] = []

        overview_lines = [
            f"Capability: {capability_id}",
            f"Namespace: {capability.get('namespace') or ''}",
            f"Title: {capability.get('title') or capability_id}",
            f"Description: {capability.get('description') or ''}",
        ]
        actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
        if actions:
            overview_lines.append("Actions: " + ", ".join(str(action.get("id") or "") for action in actions if isinstance(action, dict)))
        chunks.extend(
            self._make_chunks(
                text="\n".join(overview_lines),
                chunk_prefix=f"Capability overview for {capability_id}. ",
                metadata=RAGChunkMetadata(
                    doc_type="capability_overview",
                    collection_type=self.collection_name,
                    capability_id=capability_id,
                    action_id="",
                    source_file=path,
                    created_at=created_at,
                    updated_at=updated_at,
                    embedding_version=self.vector_store.embedding_version,
                    title=f"{capability_id} overview",
                ),
            )
        )

        for action in actions:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or "").strip()
            parameters = self._summarize_parameters(action.get("parameters"))
            examples = self._summarize_examples(action.get("examples"))
            content = "\n".join(
                [
                    f"Capability: {capability_id}",
                    f"Action: {action_id}",
                    f"Title: {action.get('title') or action_id}",
                    f"Description: {action.get('description') or ''}",
                    f"Risk: {action.get('risk_level') or 'unknown'}",
                    f"Side effect: {action.get('side_effect') or 'none'}",
                    f"Parameters: {parameters}",
                    f"Examples: {examples}",
                ]
            )
            chunks.extend(
                self._make_chunks(
                    text=content,
                    chunk_prefix=f"Capability action {action_id}. ",
                    metadata=RAGChunkMetadata(
                        doc_type="capability_action",
                        collection_type=self.collection_name,
                        capability_id=capability_id,
                        action_id=action_id,
                        source_file=path,
                        created_at=created_at,
                        updated_at=updated_at,
                        embedding_version=self.vector_store.embedding_version,
                        title=action_id,
                    ),
                )
            )
        return chunks

    def _chunks_from_readme(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        capability_id = self._capability_id_from_path(path)
        return self._make_chunks(
            text=text,
            chunk_prefix=f"Capability README for {capability_id}. ",
            metadata=RAGChunkMetadata(
                doc_type="capability_readme",
                collection_type=self.collection_name,
                capability_id=capability_id,
                action_id="",
                source_file=path,
                created_at=self._iso_now(),
                updated_at=self._iso_from_mtime(path),
                embedding_version=self.vector_store.embedding_version,
                title=f"{capability_id} README",
            ),
        )

    def _chunks_from_schema(self, path: str) -> List[RAGChunk]:
        with open(path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        capability_id = self._capability_id_from_path(path)
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        property_lines = []
        for name, definition in list(properties.items())[:20]:
            if not isinstance(definition, dict):
                continue
            property_lines.append(f"{name}: {definition.get('type', 'any')} - {definition.get('description', '')}")
        text = "\n".join(
            [
                f"Capability: {capability_id}",
                f"Schema title: {schema.get('title') or capability_id}",
                f"Required: {', '.join(str(item) for item in required) or 'none'}",
                "Properties:",
                *property_lines,
            ]
        )
        return self._make_chunks(
            text=text,
            chunk_prefix=f"Capability schema for {capability_id}. ",
            metadata=RAGChunkMetadata(
                doc_type="capability_schema",
                collection_type=self.collection_name,
                capability_id=capability_id,
                action_id="",
                source_file=path,
                created_at=self._iso_now(),
                updated_at=self._iso_from_mtime(path),
                embedding_version=self.vector_store.embedding_version,
                title=f"{capability_id} schema",
            ),
        )

    def _make_chunks(self, *, text: str, chunk_prefix: str, metadata: RAGChunkMetadata) -> List[RAGChunk]:
        parts = self.chunker.chunk(text)
        chunks: List[RAGChunk] = []
        for index, part in enumerate(parts):
            chunk_meta = RAGChunkMetadata(
                **{
                    **asdict(metadata),
                    "chunk_index": index,
                    "total_chunks": len(parts),
                }
            )
            chunk_id = hashlib.sha1(
                f"{self.collection_name}|{metadata.capability_id}|{metadata.action_id}|{metadata.doc_type}|{index}|{metadata.source_file}".encode("utf-8")
            ).hexdigest()
            chunks.append(RAGChunk(chunk_id=chunk_id, content=f"{chunk_prefix}{part}".strip(), metadata=chunk_meta))
        return chunks

    @staticmethod
    def _capability_id_from_path(path: str) -> str:
        return os.path.basename(os.path.dirname(path))

    @staticmethod
    def _summarize_parameters(parameters: object) -> str:
        if not isinstance(parameters, dict):
            return "none"
        properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
        required = parameters.get("required") if isinstance(parameters.get("required"), list) else []
        pairs = []
        for name, definition in list(properties.items())[:12]:
            if not isinstance(definition, dict):
                continue
            
            type_str = definition.get("type") or "any"
            description = definition.get("description") or ""
            enum = definition.get("enum")
            
            # Enrich with required/enum metadata
            meta = []
            if name in required:
                meta.append("required")
            if enum:
                meta.append(f"enum:{json.dumps(enum, ensure_ascii=False)}")
                
            meta_str = f" [{', '.join(meta)}]" if meta else ""
            pairs.append(f"{name} ({type_str}{meta_str}): {description}")
            
        return " | ".join(pairs) or "none"

    @staticmethod
    def _summarize_examples(examples: object) -> str:
        if not isinstance(examples, list) or not examples:
            return "none"
        fragments: List[str] = []
        for example in examples[:2]:
            if not isinstance(example, dict):
                continue
            value = example.get("input")
            if value is not None:
                fragments.append(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        return " | ".join(fragments) or "none"

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _iso_from_mtime(path: str) -> str:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()

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
