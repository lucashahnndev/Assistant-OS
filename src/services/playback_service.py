import os
import json
import hashlib
import datetime
import shutil
import threading
from typing import Dict, Any, List, Optional
from utils.logging_config import get_logger

import uuid
import logging
from config.manager import ConfigManager
from zoneinfo import ZoneInfo

logger = get_logger("PlaybackService")

class PlaybackService:
    def __init__(self, workspace_service, config_manager=None):
        self.ws = workspace_service
        self.config_manager = config_manager
        self._io_lock = threading.RLock()
        
    def _get_playback_dir(self, session_id: str, run_id: str) -> str:
        session_dir = self.ws.get_session_dir(session_id)
        playback_dir = os.path.join(session_dir, "playback", run_id)
        return playback_dir

    @staticmethod
    def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def start_run(self, session_id: str, run_id: str, title: str, source: Dict[str, str]) -> str:
        with self._io_lock:
            playback_dir = self._get_playback_dir(session_id, run_id)
            frames_dir = os.path.join(playback_dir, "frames")
            os.makedirs(frames_dir, exist_ok=True)

            manifest_path = os.path.join(playback_dir, "manifest.json")
            manifest = {
                "manifest_version": 1,
                "run_id": run_id,
                "session_id": session_id,
                "title": title,
                "source": source,
                "status": "running",
                "created_at": self._now_iso(),
                "ended_at": None,
                "total_steps": 0,
                "steps": []
            }
            self._atomic_write_json(manifest_path, manifest)

        logger.info(f"Playback run started: {run_id} in session {session_id}")
        return manifest_path

    def add_frame(self, session_id: str, run_id: str, step: int, action: Dict[str, Any], frame_bytes: bytes, width: int = 960, height: int = 540) -> Dict[str, Any]:
        with self._io_lock:
            playback_dir = self._get_playback_dir(session_id, run_id)
            frames_dir = os.path.join(playback_dir, "frames")
            try:
                os.makedirs(frames_dir, exist_ok=True)
            except Exception:
                return {}

            filename = f"frames/{step:06d}.jpg"
            frame_path = os.path.join(playback_dir, filename)

            # Save frame
            try:
                with open(frame_path, "wb") as f:
                    f.write(frame_bytes)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                return {}

            # Calculate SHA256
            sha256 = hashlib.sha256(frame_bytes).hexdigest()

            # Update manifest
            manifest_path = os.path.join(playback_dir, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                step_meta = {
                    "step": step,
                    "ts": self._now_iso(),
                    "action": action,
                    "frame_filename": filename,
                    "frame_sha256": sha256,
                    "width": width,
                    "height": height,
                    "bytes": len(frame_bytes),
                    "mime": "image/jpeg",
                }
                manifest["steps"].append(step_meta)
                manifest["total_steps"] = len(manifest["steps"])
                self._atomic_write_json(manifest_path, manifest)
                return step_meta
        return {}

    def end_run(self, session_id: str, run_id: str, status: str = "success") -> str:
        with self._io_lock:
            playback_dir = self._get_playback_dir(session_id, run_id)
            manifest_path = os.path.join(playback_dir, "manifest.json")

            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                manifest["status"] = status
                manifest["ended_at"] = self._now_iso()
                self._atomic_write_json(manifest_path, manifest)

                logger.info(f"Playback run ended: {run_id} with status {status}")
                return manifest_path
        return ""

    def cleanup_expired(self):
        """
        Garbage collection logic for playback data.
        """
        if not self.config_manager:
            return
            
        config = self.config_manager.get("playback", {})
        ttl_hours = config.get("ttl_hours", 24)
        max_total_mb = config.get("max_total_mb", 512)
        
        sessions_dir = self.ws.sessions_dir
        if not os.path.exists(sessions_dir):
            return
            
        all_runs = []
        tz_name = ConfigManager().get_timezone()
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = datetime.timezone.utc
        now = datetime.datetime.now(tz)
        
        # 1. Collect all runs
        for session_id in os.listdir(sessions_dir):
            playback_base = os.path.join(sessions_dir, session_id, "playback")
            if not os.path.exists(playback_base):
                continue
                
            for run_id in os.listdir(playback_base):
                run_path = os.path.join(playback_base, run_id)
                manifest_path = os.path.join(run_path, "manifest.json")
                
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, 'r', encoding='utf-8') as f:
                            manifest = json.load(f)
                        
                        ts_str = manifest.get("ended_at") or manifest.get("created_at")
                        ts = datetime.datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=datetime.timezone.utc)
                        
                        # Calculate size
                        total_size = 0
                        for dirpath, dirnames, filenames in os.walk(run_path):
                            for f in filenames:
                                fp = os.path.join(dirpath, f)
                                total_size += os.path.getsize(fp)
                                
                        all_runs.append({
                            "path": run_path,
                            "ts": ts,
                            "size": total_size
                        })
                    except Exception as e:
                        logger.error(f"Error reading manifest for GC in {run_path}: {e}")

        # 2. TTL Cleanup
        remaining_runs = []
        for run in all_runs:
            age = (now - run["ts"]).total_seconds() / 3600
            if age > ttl_hours:
                logger.info(f"GC: Removing expired playback run: {run['path']} (Age: {age:.1f}h)")
                shutil.rmtree(run["path"])
            else:
                remaining_runs.append(run)
                
        # 3. Size Cleanup (Max MB)
        remaining_runs.sort(key=lambda x: x["ts"]) # Oldest first
        total_mb = sum(r["size"] for r in remaining_runs) / (1024 * 1024)
        
        while total_mb > max_total_mb and remaining_runs:
            oldest = remaining_runs.pop(0)
            logger.info(f"GC: Removing old playback run to free space: {oldest['path']} (Current Total: {total_mb:.1f}MB)")
            shutil.rmtree(oldest["path"])
            total_mb -= oldest["size"] / (1024 * 1024)

    def _now_iso(self) -> str:
        tz_name = ConfigManager().get_timezone()
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = datetime.timezone.utc
        return datetime.datetime.now(tz).isoformat()
