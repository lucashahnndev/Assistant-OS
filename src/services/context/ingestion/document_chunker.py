from __future__ import annotations

from typing import List


class DocumentChunker:
    def __init__(self, chunk_size: int = 900, overlap: int = 120):
        self.chunk_size = max(240, int(chunk_size or 900))
        self.overlap = max(0, min(int(overlap or 120), self.chunk_size // 2))

    def chunk(self, text: str) -> List[str]:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return []
        if len(normalized) <= self.chunk_size:
            return [normalized]
        chunks: List[str] = []
        start = 0
        size = len(normalized)
        while start < size:
            end = min(size, start + self.chunk_size)
            if end < size:
                split = normalized.rfind(" ", start, end)
                if split > start + (self.chunk_size // 2):
                    end = split
            part = normalized[start:end].strip()
            if part:
                chunks.append(part)
            if end >= size:
                break
            start = max(end - self.overlap, start + 1)
        return chunks
