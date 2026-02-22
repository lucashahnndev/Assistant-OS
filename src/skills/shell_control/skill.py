import subprocess
import logging
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
    def _coerce_timeout(value: Any, default: int = 30) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(5, min(n, 120))

    @staticmethod
    def _trim(text: str, max_chars: int = 4000) -> str:
        text = text or ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [output truncated]"

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        cmd = params.get("command")
        if not cmd:
            return {
                "ok": False,
                "status": "error",
                "error": "MISSING_COMMAND",
                "message": "Missing command.",
                "command": "",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "text": "Erro: parâmetro 'command' é obrigatório para shell.control.execute.",
            }
        
        ws_dir = getattr(self.kernel.workspace_service, "get_workspace_dir", lambda: None)() if self.kernel and hasattr(self.kernel, "workspace_service") else None
        timeout_sec = self._coerce_timeout(params.get("timeout_sec") or self.config.get("timeout_sec", 30), default=30)
        
        try:
            logger.info(f"Executing shell command: {cmd} (cwd: {ws_dir}, timeout={timeout_sec}s)")
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=ws_dir
            )
            
            output = self._trim(result.stdout.strip())
            error = self._trim(result.stderr.strip())
            
            if result.returncode == 0:
                if output:
                    text = f"Comando executado com sucesso (exit=0).\nSaída:\n{output}"
                else:
                    text = "Comando executado com sucesso (sem saída)."
                return {
                    "ok": True,
                    "status": "success",
                    "command": cmd,
                    "cwd": ws_dir,
                    "exit_code": result.returncode,
                    "stdout": output,
                    "stderr": error,
                    "text": text,
                }

            return {
                "ok": False,
                "status": "error",
                "error": "NON_ZERO_EXIT",
                "message": f"Command exited with code {result.returncode}",
                "command": cmd,
                "cwd": ws_dir,
                "exit_code": result.returncode,
                "stdout": output,
                "stderr": error,
                "text": f"Erro: comando retornou código {result.returncode}. STDERR:\n{error or '(vazio)'}",
            }
                
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": "error",
                "error": "TIMEOUT",
                "message": f"Command exceeded timeout of {timeout_sec} seconds.",
                "command": cmd,
                "cwd": ws_dir,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "text": f"Erro: o comando excedeu o tempo limite de {timeout_sec} segundos.",
            }
        except Exception as e:
            return {
                "ok": False,
                "status": "error",
                "error": "EXCEPTION",
                "message": str(e),
                "command": cmd,
                "cwd": ws_dir,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "text": f"Erro inesperado ao executar comando shell: {str(e)}",
            }
