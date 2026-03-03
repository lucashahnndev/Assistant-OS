import hashlib
import re
from typing import Any, Dict, List


def normalize_whitespace(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clamp_chunk_size(value: Any, default: int = 700) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(100, min(n, 4000))


def clamp_chunk_overlap(value: Any, default: int = 100) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(0, min(n, 1000))


def chunk_text(text_md: Any, chunk_size: int = 700, chunk_overlap: int = 100) -> List[Dict[str, Any]]:
    """Deterministic fixed-window chunking with stable IDs from offsets+content."""
    clean = normalize_whitespace(text_md)
    if not clean:
        return []

    size = clamp_chunk_size(chunk_size, default=700)
    overlap = clamp_chunk_overlap(chunk_overlap, default=100)
    if overlap >= size:
        overlap = max(0, size // 4)

    step = max(1, size - overlap)
    chunks: List[Dict[str, Any]] = []
    cursor = 0

    while cursor < len(clean):
        end = min(len(clean), cursor + size)
        piece = clean[cursor:end].strip()
        if piece:
            digest = hashlib.sha1(f"{cursor}:{end}:{piece}".encode("utf-8")).hexdigest()[:12]
            chunks.append(
                {
                    "id": f"c_{digest}",
                    "text": piece,
                    "start": cursor,
                    "end": end,
                }
            )

        if end >= len(clean):
            break
        cursor += step

    return chunks
