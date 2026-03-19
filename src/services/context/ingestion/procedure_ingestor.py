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


class ProcedureIngestor:
    collection_name = "procedures"

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
        self.chunker = chunker or DocumentChunker(chunk_size=800, overlap=100)
        self.manifest_path = manifest_path or os.path.join(self.vector_store.base_dir, "manifests", "procedures.json")
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
        explicit = [
            os.path.join(self.repo_root, "docs", "worker_task_contract.md"),
            os.path.join(self.repo_root, "docs", "browser_control_playbook.md"),
        ]
        for path in explicit:
            if os.path.exists(path):
                yield path

        capabilities_dir = os.path.join(self.repo_root, "src", "capabilities")
        for root, _, files in os.walk(capabilities_dir):
            for filename in files:
                if filename == "README.md":
                    yield os.path.join(root, filename)

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
        source_type, capability_id = self._classify_source(path)
        for section_index, (section_title, body) in enumerate(sections):
            if not self._looks_procedural(section_title, body):
                continue
            procedure_id = self._slugify(f"{os.path.basename(path)}-{section_title}")
            created_at = self._iso_now()
            updated_at = self._iso_from_mtime(path)

            summary_text = self._normalize_text(f"{section_title}\n{body}")
            chunks.extend(
                self._make_chunks(
                    text=summary_text,
                    metadata=RAGChunkMetadata(
                        doc_type="procedure_section",
                        collection_type=self.collection_name,
                        source_file=path,
                        source_type=source_type,
                        capability_id=capability_id,
                        procedure_id=procedure_id,
                        created_at=created_at,
                        updated_at=updated_at,
                        trust_level="high",
                        embedding_version=self.vector_store.embedding_version,
                        title=section_title,
                        section=section_title,
                        tags=self._infer_tags(section_title, body),
                    ),
                )
            )
            for step_index, step in enumerate(self._extract_steps(body), start=1):
                chunks.append(
                    self._build_step_chunk(
                        path=path,
                        section_title=section_title,
                        procedure_id=procedure_id,
                        source_type=source_type,
                        capability_id=capability_id,
                        updated_at=updated_at,
                        step_index=step_index,
                        step_text=step,
                        section_index=section_index,
                    )
                )
        return chunks

    def _build_step_chunk(
        self,
        *,
        path: str,
        section_title: str,
        procedure_id: str,
        source_type: str,
        capability_id: str,
        updated_at: str,
        step_index: int,
        step_text: str,
        section_index: int,
    ) -> RAGChunk:
        title = f"{section_title} step {step_index}"
        metadata = RAGChunkMetadata(
            doc_type="procedure_step",
            collection_type=self.collection_name,
            source_file=path,
            source_type=source_type,
            capability_id=capability_id,
            procedure_id=procedure_id,
            created_at=self._iso_now(),
            updated_at=updated_at,
            trust_level="high",
            embedding_version=self.vector_store.embedding_version,
            title=title,
            step_index=step_index,
            section=section_title,
            tags=self._infer_tags(section_title, step_text),
        )
        chunk_id = hashlib.sha1(
            f"{self.collection_name}|{path}|{procedure_id}|step|{section_index}|{step_index}".encode("utf-8")
        ).hexdigest()
        content = self._normalize_text(f"Procedure: {section_title}. Step {step_index}: {step_text}")
        return RAGChunk(chunk_id=chunk_id, content=content, metadata=metadata)

    def _make_chunks(self, *, text: str, metadata: RAGChunkMetadata) -> List[RAGChunk]:
        parts = self.chunker.chunk(text)
        chunks: List[RAGChunk] = []
        for index, part in enumerate(parts):
            meta = RAGChunkMetadata(**{**asdict(metadata), "chunk_index": index, "total_chunks": len(parts)})
            chunk_id = hashlib.sha1(
                f"{self.collection_name}|{metadata.source_file}|{metadata.procedure_id}|section|{metadata.title}|{index}".encode("utf-8")
            ).hexdigest()
            chunks.append(RAGChunk(chunk_id=chunk_id, content=part, metadata=meta))
        return chunks

    @staticmethod
    def _split_markdown_sections(raw: str) -> List[Tuple[str, str]]:
        lines = raw.splitlines()
        sections: List[Tuple[str, List[str]]] = []
        current_title = "Document Overview"
        current_lines: List[str] = []
        heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
        for line in lines:
            match = heading_re.match(line)
            if match:
                if current_lines:
                    sections.append((current_title, current_lines))
                current_title = match.group(2).strip() or "Untitled Section"
                current_lines = []
                continue
            current_lines.append(line)
        if current_lines:
            sections.append((current_title, current_lines))
        return [(title, "\n".join(body).strip()) for title, body in sections if "\n".join(body).strip()]

    @staticmethod
    def _extract_steps(body: str) -> List[str]:
        steps: List[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if re.match(r"^\d+\.\s+", stripped):
                steps.append(re.sub(r"^\d+\.\s*", "", stripped))
                continue
            if stripped.startswith("- ") and len(stripped) > 8:
                steps.append(stripped[2:])
        deduped: List[str] = []
        seen = set()
        for step in steps:
            normalized = " ".join(step.split())
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return deduped[:12]

    @staticmethod
    def _looks_procedural(title: str, body: str) -> bool:
        haystack = f"{title}\n{body}".lower()
        markers = (
            "workflow",
            "flow",
            "playbook",
            "runbook",
            "checklist",
            "steps",
            "troubleshoot",
            "diagnost",
            "validation",
            "recover",
            "fluxo",
            "proced",
            "checagem",
            "recupera",
            "sintoma",
            "runbook",
        )
        return any(marker in haystack for marker in markers) or bool(re.search(r"^\d+\.\s+", body, re.MULTILINE))

    @staticmethod
    def _normalize_text(text: str) -> str:
        clean = re.sub(r"```.*?```", lambda m: " ".join(m.group(0).split()), text, flags=re.DOTALL)
        return " ".join(clean.split())

    @staticmethod
    def _classify_source(path: str) -> Tuple[str, str]:
        normalized = path.replace("\\", "/")
        if "/src/capabilities/" in normalized:
            parts = normalized.split("/src/capabilities/", 1)[1].split("/")
            return "capability_readme", parts[0]
        if normalized.endswith("browser_control_playbook.md"):
            return "playbook_doc", "browser_control"
        if normalized.endswith("worker_task_contract.md"):
            return "contract_doc", ""
        return "repo_doc", ""

    @staticmethod
    def _infer_tags(title: str, body: str) -> str:
        tags = []
        haystack = f"{title} {body}".lower()
        for tag in ("troubleshooting", "workflow", "validation", "diagnostic", "cleanup", "browser", "worker", "session"):
            if tag in haystack:
                tags.append(tag)
        return ",".join(tags)

    @staticmethod
    def _slugify(text: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
        return slug or "procedure"

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
