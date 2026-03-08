import subprocess
import logging
import time
import uuid
import threading
import queue
import shlex
from ..base import SkillBase
from typing import Dict, Any, List

logger = logging.getLogger("ShellSkill")

class ShellSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "shell"

    @property
    def name(self) -> str: return "shell"

    @property
    def actions(self) -> List[str]: return ["execute"]

    @staticmethod
    def _coerce_timeout(value: Any, default: int = 600, min_value: int = 5, max_value: int = 10800) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        low = max(1, int(min_value))
        high = max(low, int(max_value))
        return max(low, min(n, high))

    @staticmethod
    def _trim(text: str, max_chars: int = 4000) -> str:
        text = text or ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [output truncated]"

    @staticmethod
    def _append_limited(current: str, chunk: str, limit: int) -> str:
        base = current or ""
        extra = chunk or ""
        if not extra:
            return base
        merged = base + extra
        if len(merged) <= limit:
            return merged
        return merged[-limit:]

    @staticmethod
    def _touch_terminal_context(
        context: Dict[str, Any],
        *,
        terminal_id: str,
        terminal_state: Dict[str, Any],
    ) -> None:
        touch_fn = context.get("touch_work_context")
        work_id = context.get("work_id")
        if not callable(touch_fn) or not work_id:
            return
        try:
            touch_fn(
                work_id,
                {
                    "data": {
                        "shell": {
                            "last_terminal_id": terminal_id,
                            "terminals": {
                                terminal_id: terminal_state,
                            },
                        }
                    }
                },
            )
        except Exception as e:
            logger.debug(f"Failed to update shell terminal context: {e}")

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        cmd = params.get("command")
        if not cmd:
            return {
                "ok": False,
                "status": "error",
                "error_code": "MISSING_COMMAND",
                "error_details": "Missing command.",
                "command": "",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
            }
        
        ws_dir = getattr(self.kernel.workspace_service, "get_workspace_dir", lambda: None)() if self.kernel and hasattr(self.kernel, "workspace_service") else None
        normalized_cmd = str(cmd).strip()
        if normalized_cmd.startswith("sudo ") and " -n " not in f" {normalized_cmd} ":
            try:
                parts = shlex.split(normalized_cmd)
                if parts and parts[0] == "sudo":
                    parts.insert(1, "-n")
                    normalized_cmd = " ".join(shlex.quote(p) for p in parts)
            except Exception:
                normalized_cmd = normalized_cmd.replace("sudo ", "sudo -n ", 1)
        default_timeout = self._coerce_timeout(self.config.get("timeout_sec", 600), default=600, min_value=5, max_value=10800)
        max_timeout = self._coerce_timeout(self.config.get("max_timeout_sec", 10800), default=10800, min_value=30, max_value=86400)
        timeout_sec = self._coerce_timeout(
            params.get("timeout_sec") if "timeout_sec" in params else default_timeout,
            default=default_timeout,
            min_value=5,
            max_value=max_timeout,
        )
        terminal_id = f"sh_{str(uuid.uuid4())[:8]}"
        started_at = time.time()
        output_tail = ""
        output_full = ""
        line_count = 0
        full_limit = self._coerce_timeout(self.config.get("max_output_chars", 120000), default=120000, min_value=4000, max_value=1_000_000)

        self._touch_terminal_context(
            context,
            terminal_id=terminal_id,
            terminal_state={
                "id": terminal_id,
                "command": str(normalized_cmd),
                "cwd": ws_dir,
                "status": "running",
                "started_at": started_at,
                "updated_at": started_at,
                "line_count": line_count,
                "output_tail": "",
                "output_full": "",
                "transcript": f"$ {normalized_cmd}\n",
                "timeout_sec": timeout_sec,
                "exit_code": None,
            },
        )

        try:
            logger.info(f"Executing shell command: {normalized_cmd} (cwd: {ws_dir}, timeout={timeout_sec}s)")
            process = subprocess.Popen(
                normalized_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=ws_dir,
                bufsize=1,
                universal_newlines=True,
            )
            stream_queue: queue.Queue = queue.Queue()

            def _reader() -> None:
                try:
                    if process.stdout is None:
                        return
                    for line in iter(process.stdout.readline, ""):
                        stream_queue.put(line)
                finally:
                    stream_queue.put(None)

            threading.Thread(target=_reader, daemon=True).start()

            timed_out = False
            last_flush = 0.0
            while True:
                try:
                    item = stream_queue.get(timeout=0.2)
                except queue.Empty:
                    item = "__NOOP__"

                now = time.time()
                if item is None:
                    break
                if isinstance(item, str) and item != "__NOOP__":
                    output_tail = (output_tail + item)[-24000:]
                    output_full = self._append_limited(output_full, item, full_limit)
                    line_count += 1

                if process.poll() is None and (now - started_at) > timeout_sec:
                    timed_out = True
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    break

                if (now - last_flush) >= 0.4:
                    last_flush = now
                    self._touch_terminal_context(
                        context,
                        terminal_id=terminal_id,
                        terminal_state={
                            "id": terminal_id,
                            "command": str(normalized_cmd),
                            "cwd": ws_dir,
                            "status": "running",
                            "started_at": started_at,
                            "updated_at": now,
                            "line_count": line_count,
                            "output_tail": output_tail,
                            "output_full": output_full,
                            "transcript": self._append_limited(f"$ {normalized_cmd}\n", output_full, full_limit + len(normalized_cmd) + 8),
                            "timeout_sec": timeout_sec,
                            "exit_code": None,
                        },
                    )

            if timed_out and process.poll() is None:
                try:
                    process.kill()
                except Exception:
                    pass

            exit_code = process.poll()
            if exit_code is None:
                exit_code = -1

            final_now = time.time()
            if timed_out:
                self._touch_terminal_context(
                    context,
                    terminal_id=terminal_id,
                    terminal_state={
                        "id": terminal_id,
                        "command": str(normalized_cmd),
                        "cwd": ws_dir,
                        "status": "timeout",
                        "started_at": started_at,
                        "updated_at": final_now,
                        "line_count": line_count,
                        "output_tail": output_tail,
                        "output_full": output_full,
                        "transcript": self._append_limited(f"$ {normalized_cmd}\n", output_full + f"\n[timeout after {timeout_sec}s]\n", full_limit + len(normalized_cmd) + 64),
                        "timeout_sec": timeout_sec,
                        "exit_code": None,
                    },
                )
                return {
                    "ok": False,
                    "status": "error",
                    "error_code": "TIMEOUT",
                    "error_details": f"Command exceeded timeout of {timeout_sec} seconds.",
                    "command": cmd,
                    "command_effective": normalized_cmd,
                    "cwd": ws_dir,
                    "exit_code": None,
                    "stdout": self._trim(output_tail.strip()),
                    "stderr": "",
                    "terminal_id": terminal_id,
                }

            output = self._trim(output_tail.strip())
            error = ""
            final_status = "success" if exit_code == 0 else "error"
            self._touch_terminal_context(
                context,
                terminal_id=terminal_id,
                terminal_state={
                    "id": terminal_id,
                    "command": str(cmd),
                    "cwd": ws_dir,
                    "status": final_status,
                    "started_at": started_at,
                    "updated_at": final_now,
                    "line_count": line_count,
                    "output_tail": output_tail,
                    "output_full": output_full,
                    "transcript": self._append_limited(f"$ {normalized_cmd}\n", output_full + f"\n[exit {exit_code}]\n", full_limit + len(normalized_cmd) + 64),
                    "timeout_sec": timeout_sec,
                    "exit_code": exit_code,
                },
            )
            
            if exit_code == 0:
                if output:
                    text = f"Command executed successfully (exit=0).\nSaída:\n{output}"
                else:
                    text = "Command executed successfully (sem saída)."
                return {
                    "ok": True,
                    "status": "success",
                    "command": cmd,
                    "command_effective": normalized_cmd,
                    "cwd": ws_dir,
                    "exit_code": exit_code,
                    "stdout": output,
                    "stderr": error,
                    "terminal_id": terminal_id,
                }

            return {
                "ok": False,
                "status": "error",
                "error_code": "NON_ZERO_EXIT",
                "error_details": f"Command exited with code {exit_code}",
                "command": cmd,
                "command_effective": normalized_cmd,
                "cwd": ws_dir,
                "exit_code": exit_code,
                "stdout": output,
                "stderr": error,
                "terminal_id": terminal_id,
                "stdout": output,
                "stderr": error,
                "terminal_id": terminal_id,
            }
        except Exception as e:
            self._touch_terminal_context(
                context,
                terminal_id=terminal_id,
                terminal_state={
                    "id": terminal_id,
                    "command": str(normalized_cmd),
                    "cwd": ws_dir,
                    "status": "error",
                    "started_at": started_at,
                    "updated_at": time.time(),
                    "line_count": line_count,
                    "output_tail": output_tail,
                    "output_full": output_full,
                    "transcript": self._append_limited(f"$ {normalized_cmd}\n", output_full + f"\n[exception] {str(e)}\n", full_limit + len(normalized_cmd) + 80),
                    "timeout_sec": timeout_sec,
                    "exit_code": None,
                    "error_code": str(e),
                },
            )
            return {
                "ok": False,
                "status": "error",
                "error_code": "EXCEPTION",
                "error_details": str(e),
                "command": cmd,
                "command_effective": normalized_cmd,
                "cwd": ws_dir,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "terminal_id": terminal_id,
            }
