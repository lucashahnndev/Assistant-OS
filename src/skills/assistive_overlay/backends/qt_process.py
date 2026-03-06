from __future__ import annotations

import math
import multiprocessing as mp
import os
import queue
import time
from typing import Any, Dict

from .base import OverlayBackend


def _draw_focus_corners(painter: Any, x: float, y: float, w: float, h: float, corner: float) -> None:
    x2 = x + w
    y2 = y + h
    c = max(6.0, corner)

    painter.drawLine(int(x), int(y), int(x + c), int(y))
    painter.drawLine(int(x), int(y), int(x), int(y + c))

    painter.drawLine(int(x2), int(y), int(x2 - c), int(y))
    painter.drawLine(int(x2), int(y), int(x2), int(y + c))

    painter.drawLine(int(x), int(y2), int(x + c), int(y2))
    painter.drawLine(int(x), int(y2), int(x), int(y2 - c))

    painter.drawLine(int(x2), int(y2), int(x2 - c), int(y2))
    painter.drawLine(int(x2), int(y2), int(x2), int(y2 - c))


def _map_point_to_window_local(
    *,
    x: float,
    y: float,
    coordinate_space: str,
    origin_x: float,
    origin_y: float,
    screen_width: float,
    screen_height: float,
) -> tuple[float, float]:
    space = str(coordinate_space or "global").strip().lower()
    if space != "global":
        return x, y

    lx = x - origin_x
    ly = y - origin_y

    # Heuristic: when global mapping is clearly off-screen but the original
    # point fits local screen bounds, treat the point as screen-local.
    margin = 64.0
    global_out = lx < -margin or ly < -margin or lx > (screen_width + margin) or ly > (screen_height + margin)
    local_in = -margin <= x <= (screen_width + margin) and -margin <= y <= (screen_height + margin)
    if global_out and local_in:
        return x, y
    return lx, ly


def _qt_overlay_loop(command_q: Any, status_q: Any) -> None:
    try:
        from PySide6.QtCore import QTimer, Qt, QRectF, QPointF
        from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont
        from PySide6.QtWidgets import QApplication, QWidget
    except Exception as exc:
        status_q.put({"ok": False, "error": "QT_IMPORT_FAILED", "text": str(exc)})
        return

    class OverlayWindow(QWidget):
        def __init__(self, screen_index: int):
            super().__init__()
            self.screen_index = screen_index
            self.commands: Dict[str, Dict[str, Any]] = {}
            self.screen = QApplication.screens()[screen_index]
            self.setGeometry(self.screen.geometry())
            self.origin_x = int(self.screen.geometry().x())
            self.origin_y = int(self.screen.geometry().y())

            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            if hasattr(Qt.WindowType, "WindowTransparentForInput"):
                flags |= Qt.WindowType.WindowTransparentForInput
            if hasattr(Qt.WindowType, "BypassWindowManagerHint"):
                flags |= Qt.WindowType.BypassWindowManagerHint
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.showFullScreen()
            self.show()

        def set_commands(self, commands: Dict[str, Dict[str, Any]]) -> None:
            self.commands = commands
            self.update()

        def _pulse_scale(self, cmd: Dict[str, Any], now_ms: int) -> float:
            if not bool(cmd.get("pulse")):
                return 1.0
            ttl_ms = max(1, int(cmd.get("ttl_ms") or 2200))
            created_ms = int(cmd.get("created_ms") or now_ms)
            age = max(0, now_ms - created_ms)
            t = min(1.0, age / float(ttl_ms))
            cycles = 3.0
            return 1.0 + 0.08 * math.sin(t * cycles * math.pi * 2)

        def paintEvent(self, event: Any) -> None:
            now_ms = int(time.time() * 1000)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            screen_geo = self.screen.geometry()
            screen_w = float(screen_geo.width())
            screen_h = float(screen_geo.height())

            for cmd in self.commands.values():
                ctype = str(cmd.get("type") or "")
                color = QColor(str(cmd.get("color") or "#00E5FF"))
                opacity = max(0.0, min(1.0, float(cmd.get("opacity") or 0.95)))
                stroke = max(1.0, float(cmd.get("stroke_width") or 3))
                painter.setOpacity(opacity)
                painter.setPen(QPen(color, stroke))

                if ctype == "draw_text":
                    text = str(cmd.get("text") or "")
                    font_size = max(10, int(cmd.get("font_size") or 20))
                    font = QFont("Sans Serif", font_size)
                    painter.setFont(font)
                    painter.drawText(int(cmd.get("x") or 0), int(cmd.get("y") or 0), text)
                    continue

                x = float(cmd.get("x") or 0)
                y = float(cmd.get("y") or 0)
                w = float(cmd.get("width") or 0)
                h = float(cmd.get("height") or 0)
                coordinate_space = str(cmd.get("coordinate_space") or "global").strip().lower()
                x, y = _map_point_to_window_local(
                    x=x,
                    y=y,
                    coordinate_space=coordinate_space,
                    origin_x=float(self.origin_x),
                    origin_y=float(self.origin_y),
                    screen_width=screen_w,
                    screen_height=screen_h,
                )
                scale = self._pulse_scale(cmd, now_ms)
                if w > 0 and h > 0 and scale != 1.0:
                    dw = (w * scale - w) / 2.0
                    dh = (h * scale - h) / 2.0
                    x -= dw
                    y -= dh
                    w = w * scale
                    h = h * scale

                if ctype == "draw_circle":
                    radius = float(cmd.get("radius") or max(w, h) / 2.0)
                    if radius <= 0:
                        radius = 18.0
                    cx = x if w <= 0 else (x + w / 2.0)
                    cy = y if h <= 0 else (y + h / 2.0)
                    painter.drawEllipse(QPointF(cx, cy), radius, radius)
                elif ctype == "draw_rect":
                    painter.drawRect(QRectF(x, y, max(1.0, w), max(1.0, h)))
                elif ctype == "draw_focus_corners":
                    corner = max(8.0, min(24.0, min(max(1.0, w), max(1.0, h)) * 0.35))
                    _draw_focus_corners(painter, x, y, max(1.0, w), max(1.0, h), corner)
                elif ctype == "draw_line":
                    x2 = float(cmd.get("x2") or x)
                    y2 = float(cmd.get("y2") or y)
                    x2, y2 = _map_point_to_window_local(
                        x=x2,
                        y=y2,
                        coordinate_space=coordinate_space,
                        origin_x=float(self.origin_x),
                        origin_y=float(self.origin_y),
                        screen_width=screen_w,
                        screen_height=screen_h,
                    )
                    painter.drawLine(int(x), int(y), int(x2), int(y2))
                elif ctype == "draw_arrow":
                    x2 = float(cmd.get("x2") or x)
                    y2 = float(cmd.get("y2") or y)
                    x2, y2 = _map_point_to_window_local(
                        x=x2,
                        y=y2,
                        coordinate_space=coordinate_space,
                        origin_x=float(self.origin_x),
                        origin_y=float(self.origin_y),
                        screen_width=screen_w,
                        screen_height=screen_h,
                    )
                    painter.drawLine(int(x), int(y), int(x2), int(y2))
                    angle = math.atan2(y2 - y, x2 - x)
                    length = 12.0
                    a1 = angle + math.pi * 0.82
                    a2 = angle - math.pi * 0.82
                    p1 = QPointF(x2 + length * math.cos(a1), y2 + length * math.sin(a1))
                    p2 = QPointF(x2 + length * math.cos(a2), y2 + length * math.sin(a2))
                    painter.drawLine(int(x2), int(y2), int(p1.x()), int(p1.y()))
                    painter.drawLine(int(x2), int(y2), int(p2.x()), int(p2.y()))
                elif ctype == "draw_path":
                    points = cmd.get("points") if isinstance(cmd.get("points"), list) else []
                    if len(points) >= 2:
                        path = QPainterPath()
                        first = points[0]
                        fx = float(first.get("x") or 0)
                        fy = float(first.get("y") or 0)
                        fx, fy = _map_point_to_window_local(
                            x=fx,
                            y=fy,
                            coordinate_space=coordinate_space,
                            origin_x=float(self.origin_x),
                            origin_y=float(self.origin_y),
                            screen_width=screen_w,
                            screen_height=screen_h,
                        )
                        path.moveTo(fx, fy)
                        for p in points[1:]:
                            px = float(p.get("x") or 0)
                            py = float(p.get("y") or 0)
                            px, py = _map_point_to_window_local(
                                x=px,
                                y=py,
                                coordinate_space=coordinate_space,
                                origin_x=float(self.origin_x),
                                origin_y=float(self.origin_y),
                                screen_width=screen_w,
                                screen_height=screen_h,
                            )
                            path.lineTo(px, py)
                        painter.drawPath(path)

    app = QApplication([])
    screens = QApplication.screens()
    if not screens:
        status_q.put({"ok": False, "error": "NO_SCREENS", "text": "No screens detected for overlay."})
        return

    windows = [OverlayWindow(i) for i in range(len(screens))]
    commands: Dict[str, Dict[str, Any]] = {}

    def _cleanup_expired() -> None:
        now_ms = int(time.time() * 1000)
        expired = []
        for cid, cmd in commands.items():
            ttl_ms = int(cmd.get("ttl_ms") or 0)
            created_ms = int(cmd.get("created_ms") or now_ms)
            if ttl_ms > 0 and now_ms >= created_ms + ttl_ms:
                expired.append(cid)
        for cid in expired:
            commands.pop(cid, None)

    def _push_to_windows() -> None:
        per_screen: Dict[int, Dict[str, Dict[str, Any]]] = {i: {} for i in range(len(windows))}

        def _pick_screen_by_global_point(x: float, y: float) -> int:
            for idx, win in enumerate(windows):
                geo = win.screen.geometry()
                gx = int(geo.x())
                gy = int(geo.y())
                gw = int(geo.width())
                gh = int(geo.height())
                if gx <= x < gx + gw and gy <= y < gy + gh:
                    return idx
            return 0

        for cid, cmd in commands.items():
            screen_id_raw = cmd.get("screen_id")
            if screen_id_raw is None:
                screen_id = -1
            else:
                try:
                    screen_id = int(screen_id_raw)
                except Exception:
                    screen_id = -1

            if screen_id < 0 or screen_id >= len(windows):
                coordinate_space = str(cmd.get("coordinate_space") or "global").strip().lower()
                if coordinate_space == "global":
                    try:
                        px = float(cmd.get("x") or 0)
                        py = float(cmd.get("y") or 0)
                        screen_id = _pick_screen_by_global_point(px, py)
                    except Exception:
                        screen_id = 0
                else:
                    screen_id = 0
            per_screen[screen_id][cid] = cmd
        for i, win in enumerate(windows):
            win.set_commands(per_screen.get(i, {}))

    def _poll_commands() -> None:
        dirty = False
        while True:
            try:
                msg = command_q.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break

            op = str(msg.get("op") or "")
            if op == "draw":
                cmd = dict(msg.get("command") or {})
                cid = str(cmd.get("id") or "").strip()
                if cid:
                    cmd["created_ms"] = int(time.time() * 1000)
                    commands[cid] = cmd
                    dirty = True
            elif op == "clear_by_id":
                cid = str(msg.get("id") or "")
                if cid:
                    commands.pop(cid, None)
                    dirty = True
            elif op == "clear_all":
                commands.clear()
                dirty = True
            elif op == "stop":
                app.quit()
                return

        before = len(commands)
        _cleanup_expired()
        if len(commands) != before:
            dirty = True

        if dirty:
            _push_to_windows()

    timer = QTimer()
    timer.timeout.connect(_poll_commands)
    timer.start(16)

    status_q.put({"ok": True, "status": "started", "screens": len(windows)})
    app.exec()


class QtProcessOverlayBackend(OverlayBackend):
    def __init__(self, allow_wayland: bool = False):
        self.allow_wayland = bool(allow_wayland)
        self._proc: mp.Process | None = None
        self._command_q: Any = None
        self._status_q: Any = None
        self._available = False
        self._last_error = ""

    def _is_wayland_session(self) -> bool:
        if os.name != "posix":
            return False
        wayland_display = str(os.environ.get("WAYLAND_DISPLAY") or "").strip()
        session_type = str(os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
        return bool(wayland_display or session_type == "wayland")

    def start(self) -> None:
        if self._available and self._proc and self._proc.is_alive():
            return

        if self._is_wayland_session() and not self.allow_wayland:
            self._available = False
            self._last_error = "WAYLAND_DEGRADED"
            return

        self._command_q = mp.Queue()
        self._status_q = mp.Queue()
        self._proc = mp.Process(target=_qt_overlay_loop, args=(self._command_q, self._status_q), daemon=True)
        self._proc.start()

        deadline = time.time() + 2.5
        status = None
        while time.time() < deadline:
            try:
                status = self._status_q.get(timeout=0.2)
                break
            except Exception:
                pass

        if not status:
            self._available = False
            self._last_error = "OVERLAY_START_TIMEOUT"
            return

        self._available = bool(status.get("ok"))
        self._last_error = str(status.get("error") or "")

    def stop(self) -> None:
        if self._command_q:
            try:
                self._command_q.put({"op": "stop"})
            except Exception:
                pass
        if self._proc and self._proc.is_alive():
            self._proc.join(timeout=0.8)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=0.3)
        self._available = False
        self._proc = None

    def is_available(self) -> bool:
        return bool(self._available and self._proc and self._proc.is_alive())

    def draw(self, command: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "ok": False,
                "status": "error",
                "error": self._last_error or "OVERLAY_BACKEND_UNAVAILABLE",
                "text": "Overlay backend is unavailable.",
            }
        self._command_q.put({"op": "draw", "command": dict(command)})
        return {"ok": True, "status": "success", "id": command.get("id")}

    def clear_by_id(self, command_id: str) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "ok": False,
                "status": "error",
                "error": self._last_error or "OVERLAY_BACKEND_UNAVAILABLE",
                "text": "Overlay backend is unavailable.",
            }
        self._command_q.put({"op": "clear_by_id", "id": command_id})
        return {"ok": True, "status": "success", "id": command_id}

    def clear_all(self) -> Dict[str, Any]:
        if not self.is_available():
            return {
                "ok": False,
                "status": "error",
                "error": self._last_error or "OVERLAY_BACKEND_UNAVAILABLE",
                "text": "Overlay backend is unavailable.",
            }
        self._command_q.put({"op": "clear_all"})
        return {"ok": True, "status": "success"}
