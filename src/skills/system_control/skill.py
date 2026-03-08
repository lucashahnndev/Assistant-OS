import datetime
import logging
import os
import platform
from typing import Any, Dict, List

from ..base import SkillBase
from utils.toon_codec import encode_skills_list, encode_skills_describe

try:
    import pyautogui
except BaseException:
    pyautogui = None


logger = logging.getLogger("SystemSkill")


class SystemSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "system"

    @property
    def name(self) -> str:
        return "system"

    @property
    def actions(self) -> List[str]:
        return [
            "status",
            "cancel",
            "skills.list",
            "skills.list.ai",
            "skills.list.ui",
            "skills.describe",
            "skills.describe.ai",
            "skills.describe.ui",
            "screenshot",
            "info",
            "time",
            "power",
            "process.list",
            "process.kill",
            "network.status",
            "network.ping",
            "service.manage",
            "service.logs",
            "fs.list",
            "fs.read",
            "fs.write",
            "fs.delete",
            "keyboard",
        ]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "pattern": r"^/status(?:\s+(\S+))?",
                "action_id": "system.control.status",
                "handler": lambda m: {"work_id": m.group(1)},
            },
            {
                "pattern": r"^/cancel(?:\s+(\S+))?",
                "action_id": "system.control.cancel",
                "handler": lambda m: {"work_id": m.group(1)},
            },
        ]

    @staticmethod
    def _result(ok: bool, status: str, message: str = "", error_code: str = "", **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status}
        if message:
            payload["message"] = message
        if error_code:
            payload["error_code"] = error_code
        payload.update(extra)
        return payload

    @staticmethod
    def _is_error_text(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        v = value.strip().lower()
        return v.startswith("error") or v.startswith("access denied") or v.startswith("invalid action")

    @staticmethod
    def _to_int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
        try:
            out = int(value)
        except Exception:
            out = default
        if min_value is not None:
            out = max(min_value, out)
        if max_value is not None:
            out = min(max_value, out)
        return out

    def _local_action(self, action_id: str) -> str:
        if "." not in action_id:
            return action_id
        return action_id.split(".", 2)[-1]

    def _system_driver(self, context: Dict[str, Any]) -> Any:
        return context.get("system_driver") or (getattr(self.kernel, "system_driver", None) if self.kernel else None)

    def _keyboard_action(self, params: Dict[str, Any]) -> str:
        explicit = str(params.get("action") or "").strip().lower()
        if explicit:
            return explicit

        cmd = str(params.get("command") or "").lower()
        if "proximo" in cmd or "next" in cmd:
            return "next"
        if "anterior" in cmd or "prev" in cmd:
            return "prev"
        if "pausa" in cmd or "pause" in cmd or "play" in cmd:
            return "pause"
        if "aumentar volume" in cmd or "vol_up" in cmd or "volume_up" in cmd:
            return "volume_up"
        if "diminuir volume" in cmd or "vol_down" in cmd or "volume_down" in cmd:
            return "volume_down"
        if "mudo" in cmd or "mute" in cmd:
            return "mute"
        if "fechar" in cmd or "close" in cmd:
            return "close"
        return ""

    @staticmethod
    def _looks_like_skill_query(query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return False
        markers = (
            "skill",
            "skills",
            "ação",
            "acoes",
            "ações",
            "action",
            "actions",
            "namespace",
            "catalog",
            "catálogo",
            "contract",
            "contrato",
        )
        if any(m in q for m in markers):
            return True
        # Typical action-id pattern.
        if "." in q and len(q.split(".")) >= 2:
            return True
        return False

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        local = self._local_action(action_id)

        if local == "info":
            now = datetime.datetime.now()
            payload = {
                "time": now.strftime("%H:%M:%S"),
                "date": now.strftime("%Y-%m-%d"),
                "os": platform.system(),
                "dist": platform.release(),
                "user": os.getlogin() if hasattr(os, "getlogin") else "unknown",
            }
            return self._result(
                ok=True,
                status="success",
                message=f"System info: {payload['os']} {payload['dist']} ({payload['date']} {payload['time']}).",
                info=payload,
            )

        if local == "time":
            now_dt = datetime.datetime.now()
            now = now_dt.strftime("%H:%M:%S")
            today = now_dt.strftime("%Y-%m-%d")
            include_date = bool(params.get("include_date"))
            if include_date:
                return self._result(
                    ok=True,
                    status="success",
                    message=f"Current date is {today} and time is {now}.",
                    date=today,
                    time=now,
                )
            return self._result(ok=True, status="success", message=f"Current time is {now}.", date=today, time=now)

        if local in {"skills.list", "skills.list.ai", "skills.list.ui"}:
            orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
            registry = getattr(orch, "skill_registry", None)
            if not registry:
                return self._result(
                    ok=False,
                    status="error",
                    message="Skill registry not available.",
                    error_code="SKILL_REGISTRY_UNAVAILABLE",
                )

            allowed_actions = context.get("allowed_actions")
            mode = "ai"
            if local.endswith(".ui"):
                mode = "ui"
            elif local.endswith(".ai"):
                mode = "ai"
            output_format = str(params.get("format") or ("legacy" if mode == "ui" else "toon")).strip().lower()
            include_descriptions = bool(params.get("include_descriptions", mode == "ui"))
            limit = self._to_int(params.get("limit"), default=40, min_value=1, max_value=200)
            query = str(params.get("query") or "").strip().lower()
            query_ignored = False
            if mode == "ai" and query and not self._looks_like_skill_query(query):
                # Protect on-demand flow: non-skill queries (e.g. song/web text) should not empty the catalog.
                query = ""
                query_ignored = True

            rows = registry.get_catalog(
                allowed_actions=allowed_actions if isinstance(allowed_actions, list) else None,
                include_descriptions=include_descriptions,
            )
            if query:
                rows = [
                    r
                    for r in rows
                    if query in str(r.get("id", "")).lower()
                    or query in str(r.get("namespace", "")).lower()
                    or query in str(r.get("description", "")).lower()
                ]
            rows = rows[:limit]
            if output_format == "legacy":
                return self._result(
                    ok=True,
                    status="success" if rows else "empty",
                    message=f"Skill catalog returned {len(rows)} action(s).",
                    count=len(rows),
                    items=rows,
                    catalog_mode="on_demand",
                    format="legacy",
                    audience=mode,
                )

            toon = encode_skills_list(rows, include_description=include_descriptions)
            return self._result(
                ok=True,
                status="success" if rows else "empty",
                message=f"Skill catalog returned {len(rows)} action(s) in TOON format.",
                count=len(rows),
                toon=toon,
                catalog_mode="on_demand",
                format="toon",
                audience=mode,
                query_ignored=query_ignored,
            )

        if local in {"skills.describe", "skills.describe.ai", "skills.describe.ui"}:
            orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
            registry = getattr(orch, "skill_registry", None)
            if not registry:
                return self._result(
                    ok=False,
                    status="error",
                    message="Skill registry not available.",
                    error_code="SKILL_REGISTRY_UNAVAILABLE",
                )

            requested: List[str] = []
            one = str(params.get("action_id") or "").strip()
            many = params.get("action_ids")
            if one:
                requested.append(one)
            if isinstance(many, list):
                for item in many:
                    v = str(item or "").strip()
                    if v:
                        requested.append(v)

            if not requested:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'action_id' or 'action_ids'.",
                    error_code="MISSING_ACTION_ID",
                )

            allowed_actions = context.get("allowed_actions")
            mode = "ai"
            if local.endswith(".ui"):
                mode = "ui"
            elif local.endswith(".ai"):
                mode = "ai"
            output_format = str(params.get("format") or ("legacy" if mode == "ui" else "toon")).strip().lower()
            allowed_set = set(allowed_actions) if isinstance(allowed_actions, list) else None

            details: List[Dict[str, Any]] = []
            for action_id in requested[:50]:
                resolved = registry.resolve_action_id(action_id) or action_id
                if allowed_set is not None and resolved not in allowed_set:
                    details.append(
                        {
                            "id": action_id,
                            "ok": False,
                            "error_code": "ACTION_NOT_ALLOWED",
                        }
                    )
                    continue
                metadata = registry.get_action_metadata(resolved)
                details.append(
                    {
                        "id": resolved,
                        "ok": bool(metadata),
                        "metadata": metadata or {},
                    }
                )

            if output_format == "legacy":
                return self._result(
                    ok=True,
                    status="success",
                    message=f"Returned details for {len(details)} action(s).",
                    count=len(details),
                    items=details,
                    format="legacy",
                    audience=mode,
                )

            toon = encode_skills_describe(details)
            return self._result(
                ok=True,
                status="success",
                message=f"Returned details for {len(details)} action(s) in TOON format.",
                count=len(details),
                toon=toon,
                format="toon",
                audience=mode,
            )

        sd = self._system_driver(context)
        if not sd:
            return self._result(
                ok=False,
                status="error",
                message="SystemDriver not available.",
                error_code="SYSTEM_DRIVER_UNAVAILABLE",
                message="System driver is required for this action.",
            )

        if local == "status":
            work_id = params.get("work_id")
            scheduler = getattr(self.kernel, "scheduler", None) if self.kernel else None
            if work_id:
                if not scheduler:
                    return self._result(
                        ok=False,
                        status="error",
                        message="System status unavailable (local execution).",
                        error_code="STATUS_UNAVAILABLE",
                    )
                work = scheduler.get_work(work_id)
                if not work:
                    return self._result(
                        ok=True,
                        status="empty",
                        message=f"Work '{work_id}' not found.",
                        work_id=work_id,
                        work=None,
                    )
                data = work.to_dict() if hasattr(work, "to_dict") else work
                return self._result(
                    ok=True,
                    status="success",
                    message=f"Status loaded for work '{work_id}'.",
                    work_id=work_id,
                    work=data,
                )

            if not scheduler:
                return self._result(
                    ok=False,
                    status="error",
                    message="System status unavailable (local execution).",
                    error_code="STATUS_UNAVAILABLE",
                )

            active = scheduler.list_active_works() if scheduler else []
            return self._result(
                ok=True,
                status="success" if active else "empty",
                message=f"Active works: {len(active)}.",
                count=len(active),
                works=active,
            )

        if local == "cancel":
            work_id = str(params.get("work_id") or "").strip()
            scheduler = getattr(self.kernel, "scheduler", None) if self.kernel else None
            if not work_id:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'work_id'.",
                    error_code="MISSING_WORK_ID",
                )
            if not scheduler:
                return self._result(
                    ok=False,
                    status="error",
                    message="Kernel scheduler not available.",
                    error_code="SCHEDULER_UNAVAILABLE",
                )
            scheduler.request_cancel(work_id)
            return self._result(
                ok=True,
                status="success",
                message=f"Cancellation requested for work '{work_id}'.",
                work_id=work_id,
            )

        if local == "screenshot":
            sid = context.get("session_id")
            filename = str(params.get("output_file") or params.get("filename") or "screenshot.png")
            screenshot_path = sd.take_screenshot(filename, session_id=sid)
            if self._is_error_text(screenshot_path):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Screenshot failed: {screenshot_path}",
                    error_code="SCREENSHOT_FAILED",
                    message=str(screenshot_path),
                )
            return self._result(
                ok=True,
                status="success",
                message=f"Screenshot saved to {screenshot_path}.",
                path=screenshot_path,
                session_id=sid,
            )

        if local == "power":
            command = str(params.get("action") or params.get("command") or "").lower()
            if "reboot" in command or "restart" in command:
                out = sd.power_reboot()
                return self._result(
                    ok=not self._is_error_text(out),
                    status="success" if not self._is_error_text(out) else "error",
                    message=str(out),
                    action="reboot",
                    output=out,
                )
            if "shutdown" in command or "off" in command:
                out = sd.power_shutdown()
                return self._result(
                    ok=not self._is_error_text(out),
                    status="success" if not self._is_error_text(out) else "error",
                    message=str(out),
                    action="shutdown",
                    output=out,
                )
            return self._result(
                ok=False,
                status="error",
                message=f"Unknown power command: '{command}'. Use 'reboot' or 'shutdown'.",
                error_code="UNKNOWN_POWER_COMMAND",
                message="Use reboot/restart or shutdown/off",
            )

        if local == "process.list":
            name_contains = params.get("name_contains")
            user = params.get("user")
            sort = str(params.get("sort") or "cpu")
            items = sd.list_processes(name_contains, user, sort)
            if not isinstance(items, list):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Unable to list processes: {items}",
                    error_code="PROCESS_LIST_FAILED",
                    message=str(items),
                )
            return self._result(
                ok=True,
                status="success" if items else "empty",
                message=f"Processes listed: {len(items)}.",
                count=len(items),
                results=items,
            )

        if local == "process.kill":
            pid = params.get("pid")
            if pid is None:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'pid'.",
                    error_code="MISSING_PID",
                )
            signal = str(params.get("signal") or "TERM")
            out = sd.kill_process(int(pid), signal)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out),
                pid=int(pid),
                signal=signal,
                output=out,
            )

        if local == "network.status":
            out = sd.net_status()
            if isinstance(out, str) and self._is_error_text(out):
                return self._result(
                    ok=False,
                    status="error",
                    message=f"Network status failed: {out}",
                    error_code="NETWORK_STATUS_FAILED",
                    message=out,
                )
            return self._result(
                ok=True,
                status="success",
                message="Network status retrieved.",
                result=out,
            )

        if local == "network.ping":
            host = str(params.get("host") or "").strip()
            if not host:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'host'.",
                    error_code="MISSING_HOST",
                )
            count = self._to_int(params.get("count"), default=4, min_value=1, max_value=10)
            out = sd.net_ping(host, count)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=f"Ping executed for {host} ({count} packets)." if ok else str(out),
                host=host,
                count=count,
                output=out,
            )

        if local == "service.manage":
            unit = str(params.get("unit") or "").strip()
            action = str(params.get("action") or "").strip()
            if not unit or not action:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameters 'unit' and/or 'action'.",
                    error_code="MISSING_SERVICE_PARAMS",
                )
            out = sd.service_action(unit, action)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out) if out else f"Service action '{action}' executed for '{unit}'.",
                unit=unit,
                action=action,
                output=out,
            )

        if local == "service.logs":
            unit = str(params.get("unit") or "").strip()
            if not unit:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'unit'.",
                    error_code="MISSING_UNIT",
                )
            lines = self._to_int(params.get("lines"), default=50, min_value=1, max_value=500)
            out = sd.service_logs(unit, lines)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=f"Service logs retrieved for '{unit}' ({lines} lines)." if ok else str(out),
                unit=unit,
                lines=lines,
                logs=out if ok else None,
                output=out if not ok else None,
            )

        if local == "fs.list":
            path = str(params.get("path") or params.get("filepath") or ".")
            out = sd.fs_list(path)
            if isinstance(out, str) and self._is_error_text(out):
                return self._result(
                    ok=False,
                    status="error",
                    message=str(out),
                    error_code="FS_LIST_FAILED",
                    path=path,
                )
            if isinstance(out, list):
                return self._result(
                    ok=True,
                    status="success" if out else "empty",
                    message=f"Listed {len(out)} items in '{path}'.",
                    path=path,
                    count=len(out),
                    results=out,
                )
            return self._result(
                ok=False,
                status="error",
                message=f"Unexpected fs.list output for '{path}'.",
                error_code="FS_LIST_INVALID_OUTPUT",
                path=path,
                output=out,
            )

        if local == "fs.read":
            path = str(params.get("path") or params.get("filepath") or "").strip()
            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'path'.",
                    error_code="MISSING_PATH",
                )
            start = self._to_int(params.get("start"), default=1, min_value=1)
            end = params.get("end")
            end_value = self._to_int(end, default=start, min_value=start) if end is not None else None
            out = sd.fs_read(path, start, end_value)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=f"Read file '{path}'." if ok else str(out),
                path=path,
                start=start,
                end=end_value,
                content=out if ok else None,
                output=out if not ok else None,
            )

        if local == "fs.write":
            path = str(params.get("path") or params.get("filepath") or "").strip()
            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'path'.",
                    error_code="MISSING_PATH",
                )
            content = str(params.get("content") or "")
            out = sd.fs_write(path, content)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out),
                path=path,
                bytes_written=len(content.encode("utf-8")),
                output=out,
            )

        if local == "fs.delete":
            path = str(params.get("path") or params.get("filepath") or "").strip()
            if not path:
                return self._result(
                    ok=False,
                    status="error",
                    message="Missing required parameter 'path'.",
                    error_code="MISSING_PATH",
                )
            out = sd.fs_delete(path)
            ok = not self._is_error_text(out)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                message=str(out),
                path=path,
                output=out,
            )

        if local == "keyboard":
            if not pyautogui:
                return self._result(
                    ok=False,
                    status="error",
                    message="Keyboard control (pyautogui) not available.",
                    error_code="PYAUTOGUI_UNAVAILABLE",
                )

            kb_action = self._keyboard_action(params)
            if kb_action == "next":
                pyautogui.hotkey("fn", "right")
                return self._result(ok=True, status="success", message="Skipping to next.", action="next")
            if kb_action == "prev":
                pyautogui.hotkey("fn", "left")
                return self._result(ok=True, status="success", message="Going to previous.", action="prev")
            if kb_action == "pause":
                pyautogui.press("space")
                return self._result(ok=True, status="success", message="Playback paused/resumed.", action="pause")
            if kb_action == "volume_up":
                for _ in range(5):
                    pyautogui.press("volumeup")
                return self._result(ok=True, status="success", message="Volume increased.", action="volume_up")
            if kb_action == "volume_down":
                for _ in range(5):
                    pyautogui.press("volumedown")
                return self._result(ok=True, status="success", message="Volume decreased.", action="volume_down")
            if kb_action == "mute":
                pyautogui.press("volumemute")
                return self._result(ok=True, status="success", message="Mute toggled.", action="mute")
            if kb_action == "close":
                pyautogui.hotkey("alt", "f4")
                return self._result(ok=True, status="success", message="Window closed.", action="close")
            return self._result(
                ok=False,
                status="error",
                message="Unknown keyboard command. Use action: next|prev|pause|volume_up|volume_down|mute|close.",
                error_code="UNKNOWN_KEYBOARD_COMMAND",
            )

        return self._result(
            ok=False,
            status="error",
            message=f"Unknown system action: {action_id}",
            error_code="UNKNOWN_ACTION",
            message=f"Unknown action: {action_id}",
        )
