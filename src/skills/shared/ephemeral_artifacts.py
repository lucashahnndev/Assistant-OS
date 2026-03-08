from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from typing import Any


def execution_token_from_context(context: dict[str, Any] | None) -> str:
    raw = ""
    if isinstance(context, dict):
        raw = str(
            context.get("work_id")
            or context.get("execution_id")
            or context.get("run_id")
            or ""
        ).strip()
    if not raw:
        raw = uuid.uuid4().hex
    token = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-")
    return token or uuid.uuid4().hex


def build_temp_media_filename(prefix: str, context: dict[str, Any] | None, ext: str = ".png") -> str:
    token = execution_token_from_context(context)
    ts_ms = int(time.time() * 1000)
    clean_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(prefix or "artifact")).strip("-") or "artifact"
    return f"temp/{token}/{clean_prefix}_{ts_ms}{ext}"


def prune_temp_artifacts_from_path(path: str, ttl_ms: int) -> int:
    """
    Removes expired execution folders under .../media/image/temp based on newest mtime in each folder.
    Returns number of removed execution directories.
    """
    if not path or ttl_ms <= 0:
        return 0

    norm = os.path.normpath(path)
    marker = os.path.join("media", "image", "temp")
    marker_idx = norm.find(marker)
    if marker_idx < 0:
        return 0

    temp_root = norm[: marker_idx + len(marker)]
    if not os.path.isdir(temp_root):
        return 0

    cutoff = time.time() - (float(ttl_ms) / 1000.0)
    removed = 0

    for entry in os.scandir(temp_root):
        if not entry.is_dir(follow_symlinks=False):
            continue
        newest_mtime = 0.0
        for root, _, files in os.walk(entry.path):
            try:
                newest_mtime = max(newest_mtime, os.path.getmtime(root))
            except Exception:
                pass
            for name in files:
                fpath = os.path.join(root, name)
                try:
                    newest_mtime = max(newest_mtime, os.path.getmtime(fpath))
                except Exception:
                    continue
        if newest_mtime <= 0.0:
            newest_mtime = time.time()
        if newest_mtime < cutoff:
            shutil.rmtree(entry.path, ignore_errors=True)
            removed += 1

    return removed
