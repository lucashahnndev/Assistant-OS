import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

from .playwright_mcp_adapter import PlaywrightMCPAdapter
from .schemas import ToonResponse

logger = logging.getLogger("aosd.capabilities.browser_control.runtime_playwright")


class BrowserRuntimePlaywright:
    """Playwright-based runtime compatible with the existing planner contract."""

    def __init__(
        self,
        chrome_path: str,
        base_profile_path: str,
        overlay_profile_parent: str,
        desktop_cache_dir: str,
        desktop_launch_enabled: bool,
        extension_install_mode: str,
        extension_fallback_enabled: bool,
        headless: bool,
        muted: bool,
        app_mode: bool,
        launch_url: str,
        humanize_input_enabled: bool,
        visual_cursor_enabled: bool,
        tab_user_lock_enabled: bool,
        tab_control_bar_enabled: bool,
        agent_name: str,
        playwright_transport_mode: str = "local",
        playwright_mcp_endpoint: str = "",
        playwright_mcp_fallback_to_local: bool = True,
    ):
        self.chrome_path = str(chrome_path or "")
        self.base_profile_path = str(base_profile_path or "")
        self.overlay_profile_parent = str(overlay_profile_parent or "")
        self.desktop_cache_dir = str(desktop_cache_dir or "")
        self.desktop_launch_enabled = bool(desktop_launch_enabled)
        self.extension_install_mode = str(extension_install_mode or "auto")
        self.extension_fallback_enabled = bool(extension_fallback_enabled)
        self.headless = bool(headless)
        self.muted = bool(muted)
        self.app_mode = bool(app_mode)
        self.launch_url = str(launch_url or "about:blank")
        self.humanize_input_enabled = bool(humanize_input_enabled)
        self.visual_cursor_enabled = bool(visual_cursor_enabled)
        self.tab_user_lock_enabled = bool(tab_user_lock_enabled)
        self.tab_control_bar_enabled = bool(tab_control_bar_enabled)
        self.agent_name = str(agent_name or "Agent")
        self.playwright_transport_mode = str(playwright_transport_mode or "local").strip().lower()
        self.playwright_mcp_endpoint = str(playwright_mcp_endpoint or "").strip()
        # Legacy compatibility flag kept for config/API stability only.
        # Local fallback is intentionally disabled in MCP mode (fail-fast).
        self.playwright_mcp_fallback_to_local = False
        if bool(playwright_mcp_fallback_to_local):
            logger.warning(
                "playwright_mcp_fallback_to_local is deprecated and ignored; MCP transport now runs in strict mode."
            )

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._overlay_profile_path = ""

        self._trace_id = f"pw_{uuid.uuid4().hex[:12]}"
        self.target_id = ""
        self.ws_url = ""
        self.remote_debugging_port = None
        self._mcp_active_tab_index = 0

        self._agent_control_active = False
        self._paused = False
        self._resume_requested = False
        self._resume_context = ""
        self._step_context: Dict[str, str] = {"step_id": "", "trace_id": self._trace_id}
        self._trace_context: Dict[str, str] = {
            "session_id": "",
            "work_id": "",
            "interface": "",
            "channel": "",
        }
        self._transport_mode_effective = "local"
        self._mcp_adapter: Optional[PlaywrightMCPAdapter] = None

    @staticmethod
    def _mcp_target_from_index(index: int) -> str:
        idx = int(index or 0)
        if idx < 0:
            idx = 0
        return f"mcp_tab_{idx}"

    @staticmethod
    def _mcp_index_from_target(target_id: str) -> Optional[int]:
        raw = str(target_id or "").strip().lower()
        if not raw.startswith("mcp_tab_"):
            return None
        suffix = raw.replace("mcp_tab_", "", 1).strip()
        try:
            idx = int(suffix)
        except Exception:
            return None
        return idx if idx >= 0 else None

    def _resolve_transport_mode(self) -> str:
        mode = str(self.playwright_transport_mode or "local").strip().lower()
        if mode not in {"local", "mcp"}:
            mode = "local"
        return mode

    async def launch(self) -> None:
        configured_mode = self._resolve_transport_mode()
        if configured_mode == "mcp":
            if not self.playwright_mcp_endpoint:
                raise RuntimeError(
                    "Playwright MCP mode selected but playwright_mcp_endpoint is missing. "
                    "Set a valid endpoint or switch explicitly to playwright_transport_mode=local."
                )
            self._mcp_adapter = PlaywrightMCPAdapter(self.playwright_mcp_endpoint)
            self._transport_mode_effective = "mcp"
            try:
                tabs_meta = await self._mcp_adapter.list_tabs()
                tabs = tabs_meta.get("tabs") if isinstance(tabs_meta.get("tabs"), list) else []
                active_index = int(tabs_meta.get("active_index", 0) or 0)
                if tabs:
                    active_index = max(0, min(active_index, len(tabs) - 1))
                else:
                    active_index = 0
                self._mcp_active_tab_index = active_index
                self.target_id = self._mcp_target_from_index(active_index)
            except Exception:
                self._mcp_active_tab_index = 0
                self.target_id = self._mcp_target_from_index(0)
            logger.info("Playwright runtime using MCP transport endpoint: %s", self.playwright_mcp_endpoint)
            return
        else:
            self._transport_mode_effective = "local"

        os.makedirs(self.overlay_profile_parent, exist_ok=True)
        os.makedirs(self.desktop_cache_dir, exist_ok=True)
        self._overlay_profile_path = os.path.join(self.overlay_profile_parent, f"pw_{int(time.time() * 1000)}")
        os.makedirs(self._overlay_profile_path, exist_ok=True)

        self._playwright = await async_playwright().start()

        launch_kwargs: Dict[str, Any] = {
            "headless": self.headless,
            "args": ["--no-default-browser-check", "--disable-notifications"],
        }
        if self.muted:
            launch_kwargs["args"].append("--mute-audio")
        if self.chrome_path and os.path.exists(self.chrome_path):
            launch_kwargs["executable_path"] = self.chrome_path

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(ignore_https_errors=True)
        self._page = await self._context.new_page()
        self.target_id = f"pw_page_{id(self._page)}"

        try:
            await self._page.goto(self.launch_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            logger.warning("Playwright launch goto failed (%s): %s", self.launch_url, e)

    async def close(self) -> None:
        self._mcp_adapter = None
        try:
            if self._context:
                await self._context.close()
        finally:
            self._context = None
            self._page = None
        try:
            if self._browser:
                await self._browser.close()
        finally:
            self._browser = None
        try:
            if self._playwright:
                await self._playwright.stop()
        finally:
            self._playwright = None

    def force_close(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self.close())
                return
        except RuntimeError:
            pass
        try:
            asyncio.run(self.close())
        except Exception:
            pass

    def set_step_context(self, step_id: str, trace_id: str) -> None:
        self._step_context = {
            "step_id": str(step_id or ""),
            "trace_id": str(trace_id or self._trace_id),
        }

    def set_trace_context(self, session_id: str, work_id: str, interface: str, channel: str) -> None:
        self._trace_context = {
            "session_id": str(session_id or ""),
            "work_id": str(work_id or ""),
            "interface": str(interface or ""),
            "channel": str(channel or ""),
        }

    async def set_agent_control_active(self, active: bool) -> None:
        self._agent_control_active = bool(active)

    async def get_tab_control_state(self) -> Dict[str, Any]:
        return {
            "paused": bool(self._paused),
            "resume_requested": bool(self._resume_requested),
            "resume_context": str(self._resume_context or ""),
        }

    async def _wait_for_load(self) -> None:
        if self._transport_mode_effective == "mcp":
            await asyncio.sleep(0.1)
            return
        if not self._page:
            return
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

    async def _get_current_url(self) -> str:
        if self._transport_mode_effective == "mcp":
            info = await self.get_page_info()
            return str(info.get("url", "") or "")
        if not self._page:
            return ""
        return str(self._page.url or "")

    async def _get_current_title(self) -> str:
        if self._transport_mode_effective == "mcp":
            info = await self.get_page_info()
            return str(info.get("title", "") or "")
        if not self._page:
            return ""
        try:
            return str(await self._page.title())
        except Exception:
            return ""

    async def get_page_info(self) -> Dict[str, Any]:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return {"url": "", "title": "", "viewport": {"w": 0, "h": 0}}
            return await self._mcp_adapter.get_page_info()
        if not self._page:
            return {"url": "", "title": "", "viewport": {"w": 0, "h": 0}}
        try:
            payload = await self._page.evaluate(
                """() => ({
                  url: String(window.location.href || ""),
                  title: String(document.title || ""),
                  w: Number(window.innerWidth || 0),
                  h: Number(window.innerHeight || 0),
                })"""
            )
            if not isinstance(payload, dict):
                payload = {}
            return {
                "url": str(payload.get("url", "") or ""),
                "title": str(payload.get("title", "") or ""),
                "viewport": {
                    "w": int(payload.get("w", 0) or 0),
                    "h": int(payload.get("h", 0) or 0),
                },
            }
        except Exception:
            return {
                "url": await self._get_current_url(),
                "title": await self._get_current_title(),
                "viewport": {"w": 0, "h": 0},
            }

    async def _call_cdp(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._transport_mode_effective == "mcp":
            if str(method or "") != "Runtime.evaluate":
                raise RuntimeError(f"Unsupported CDP compatibility method over MCP transport: {method}")
            if self._mcp_adapter is None:
                raise RuntimeError("MCP adapter is not initialized")
            expression = str((params or {}).get("expression") or "")
            out = await self._mcp_adapter._call_tool_preferred(
                ["browser_evaluate", "browser_run_code"],
                {"function": f"() => ({expression})", "code": f"async (page) => page.evaluate({json.dumps(expression)})"},
            )
            payload = PlaywrightMCPAdapter._coerce_result_payload(out)
            return {"result": {"value": payload.get("value", payload)}}
        if not self._page:
            raise RuntimeError("Playwright page is not available")
        if str(method or "") != "Runtime.evaluate":
            raise RuntimeError(f"Unsupported CDP compatibility method: {method}")

        expression = str((params or {}).get("expression") or "")
        value = await self._page.evaluate(expression)
        return {"result": {"value": value}}

    def get_connection_metadata(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "ws_url": self.ws_url,
            "debug_port": self.remote_debugging_port,
            "app_mode": bool(self.app_mode),
            "launch_url": self.launch_url,
            "backend": "playwright",
            "transport_mode_configured": self._resolve_transport_mode(),
            "transport_mode_effective": self._transport_mode_effective,
            "mcp_endpoint": self.playwright_mcp_endpoint,
            "mcp_fallback_to_local": bool(self.playwright_mcp_fallback_to_local),
            "mcp_calls_total": int(self._mcp_adapter.calls_total) if self._mcp_adapter is not None else 0,
            "mcp_tab_index": int(self._mcp_active_tab_index) if self._transport_mode_effective == "mcp" else None,
        }

    async def attach_to_target(self, target_id: str) -> bool:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return False
            idx = self._mcp_index_from_target(target_id)
            if idx is None:
                return False
            try:
                await self._mcp_adapter.select_tab(idx)
                self._mcp_active_tab_index = idx
                self.target_id = self._mcp_target_from_index(idx)
                return True
            except Exception:
                return False
        return bool(target_id and target_id == self.target_id and self._page is not None)

    async def attach_to_any_page(self, preferred_targets: Optional[List[str]] = None) -> str:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return ""
            preferred = preferred_targets or []
            for wanted in preferred:
                idx = self._mcp_index_from_target(str(wanted or ""))
                if idx is None:
                    continue
                try:
                    await self._mcp_adapter.select_tab(idx)
                    self._mcp_active_tab_index = idx
                    self.target_id = self._mcp_target_from_index(idx)
                    return self.target_id
                except Exception:
                    continue
            try:
                tabs_meta = await self._mcp_adapter.list_tabs()
                tabs = tabs_meta.get("tabs") if isinstance(tabs_meta.get("tabs"), list) else []
                active_index = int(tabs_meta.get("active_index", 0) or 0)
                if tabs:
                    active_index = max(0, min(active_index, len(tabs) - 1))
                    await self._mcp_adapter.select_tab(active_index)
                else:
                    active_index = 0
                self._mcp_active_tab_index = active_index
                self.target_id = self._mcp_target_from_index(active_index)
                return self.target_id
            except Exception:
                return str(self.target_id or "")
        if self._page is None:
            return ""
        return str(self.target_id or "")

    async def open_new_tab(self, launch_url: str) -> str:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return ""
            created = await self._mcp_adapter.create_tab(str(launch_url or "about:blank"))
            idx = int(created.get("index", self._mcp_active_tab_index) or self._mcp_active_tab_index)
            if idx < 0:
                idx = 0
            self._mcp_active_tab_index = idx
            self.target_id = self._mcp_target_from_index(idx)
            return self.target_id
        if not self._context:
            return ""
        self._page = await self._context.new_page()
        self.target_id = f"pw_page_{id(self._page)}"
        try:
            await self._page.goto(str(launch_url or "about:blank"), wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        return self.target_id

    async def get_page_signature(self) -> Dict[str, Any]:
        if self._transport_mode_effective == "mcp":
            info = await self.get_page_info()
            return {
                "url": str(info.get("url", "") or ""),
                "title": str(info.get("title", "") or ""),
                "readyState": "unknown",
                "domCount": 0,
                "bodyTextLen": 0,
            }
        if not self._page:
            return {}
        try:
            return await self._page.evaluate(
                """() => ({
                  url: location.href,
                  title: document.title,
                  readyState: document.readyState,
                  domCount: document.querySelectorAll('*').length,
                  bodyTextLen: (document.body && document.body.innerText ? document.body.innerText.length : 0),
                })"""
            )
        except Exception:
            return {}

    async def get_skeletal_dom(self) -> Dict[str, Any]:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return {"nodes": [], "markers": [], "focus": {}, "total_count": 0, "viewport_count": 0}
            return await self._mcp_adapter.get_skeletal_dom()
        if not self._page:
            return {"nodes": [], "markers": [], "focus": {}, "total_count": 0, "viewport_count": 0}

        payload = await self._page.evaluate(
            """() => {
              const vw = window.innerWidth || 1280;
              const vh = window.innerHeight || 720;
              const all = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role],h1,h2,h3,p,span,div'));
              const nodes = [];
              const markers = [];
              let idx = 0;
              for (const el of all.slice(0, 260)) {
                const rect = el.getBoundingClientRect();
                const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 140);
                const role = (el.getAttribute('role') || '').trim();
                const tag = (el.tagName || '').toLowerCase();
                const inViewport = rect.width > 1 && rect.height > 1 && rect.bottom >= 0 && rect.right >= 0 && rect.top <= vh && rect.left <= vw;
                const node = {
                  id: `pw_node_${idx++}`,
                  tag,
                  role,
                  text,
                  inViewport,
                  bbox: {x: Math.max(0, rect.left), y: Math.max(0, rect.top), w: Math.max(0, rect.width), h: Math.max(0, rect.height)}
                };
                nodes.push(node);
                if ((tag === 'h1' || tag === 'h2' || role === 'heading') && text) {
                  markers.push({text, tag, role});
                }
              }

              const ae = document.activeElement;
              const focus = ae ? {
                tag: (ae.tagName || '').toLowerCase(),
                id: ae.id || '',
                role: ae.getAttribute ? (ae.getAttribute('role') || '') : '',
              } : {};

              return {
                nodes,
                markers,
                focus,
                total_count: nodes.length,
                viewport_count: nodes.filter(n => !!n.inViewport).length,
              };
            }"""
        )
        return payload if isinstance(payload, dict) else {"nodes": [], "markers": [], "focus": {}, "total_count": 0, "viewport_count": 0}

    async def capture_screenshot_to_file(self, image_format: str = "png", quality: int = 80) -> str:
        if self._transport_mode_effective == "mcp":
            _ = quality
            if self._mcp_adapter is None:
                return ""
            return await self._mcp_adapter.capture_screenshot_to_file(image_format=image_format)
        if not self._page:
            return ""
        fmt = str(image_format or "png").lower()
        if fmt not in {"png", "jpeg"}:
            fmt = "png"
        suffix = ".jpg" if fmt == "jpeg" else ".png"
        fd, path = tempfile.mkstemp(prefix="aosd_pw_", suffix=suffix)
        os.close(fd)
        kwargs: Dict[str, Any] = {"path": path, "type": fmt, "full_page": False}
        if fmt == "jpeg":
            kwargs["quality"] = int(max(20, min(95, quality)))
        await self._page.screenshot(**kwargs)
        return path

    async def capture_screenshot_bytes(self) -> bytes:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return b""
            return await self._mcp_adapter.capture_screenshot_bytes()
        if not self._page:
            return b""
        return await self._page.screenshot(type="jpeg", quality=70, full_page=False)

    async def navigate(self, url: str) -> ToonResponse:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return self._error_response("navigate", f"No MCP adapter for navigate to {url}")
            t0 = time.time()
            target = str(url or "").strip() or "about:blank"
            await self._mcp_adapter.navigate(target)
            info = await self.get_page_info()
            if not self.target_id:
                self.target_id = self._mcp_target_from_index(self._mcp_active_tab_index)
            return self._success_response(
                action="navigate",
                elapsed=time.time() - t0,
                message=f"Navigated to {target}",
                result_data={"url": str(info.get("url", target) or target), "kind": "navigate_action_receipt_v1"},
            )
        if not self._page:
            return self._error_response("navigate", f"No page for navigate to {url}")
        t0 = time.time()
        target = str(url or "").strip() or "about:blank"
        await self._page.goto(target, wait_until="domcontentloaded", timeout=25000)
        return self._success_response(
            action="navigate",
            elapsed=time.time() - t0,
            message=f"Navigated to {target}",
            result_data={"url": str(self._page.url or target), "kind": "navigate_action_receipt_v1"},
        )

    async def click(self, x: Optional[float] = None, y: Optional[float] = None, selector: str = "") -> ToonResponse:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return self._error_response("click", "No MCP adapter for click")
            t0 = time.time()
            raw = await self._mcp_adapter.click(x=x, y=y, selector=selector)
            payload = PlaywrightMCPAdapter._coerce_result_payload(raw)
            hit_after = payload.get("hit_after") if isinstance(payload.get("hit_after"), dict) else {}
            delivered = bool(payload.get("clicked", payload.get("ok", True)))
            fallback_clicked = bool(payload.get("fallback_clicked", False))
            return self._success_response(
                action="click",
                elapsed=time.time() - t0,
                result_data={
                    "kind": "click_action_receipt_v1",
                    "delivered": bool(delivered),
                    "hit_after": hit_after,
                    "fallback_clicked": bool(fallback_clicked),
                },
            )
        if not self._page:
            return self._error_response("click", "No page for click")
        t0 = time.time()
        delivered = False
        fallback_clicked = False

        if selector:
            locator = self._page.locator(selector).first
            await locator.click(timeout=7000)
            delivered = True
        else:
            cx = float(x if x is not None else 0)
            cy = float(y if y is not None else 0)
            await self._page.mouse.click(cx, cy)
            delivered = True

        hit_after = await self._page.evaluate(
            """([x, y]) => {
              const el = document.elementFromPoint(x, y);
              if (!el) return {};
              const text = (el.innerText || el.textContent || '').trim().slice(0, 160);
              const interactive = el.closest('a,button,input,textarea,select,[role="button"],[role="link"]');
              return {
                top_tag: (el.tagName || '').toLowerCase(),
                top_text: text,
                has_interactive_ancestor: !!interactive,
                interactive_tag: interactive ? (interactive.tagName || '').toLowerCase() : '',
              };
            }""",
            [float(x or 0), float(y or 0)],
        ) if x is not None and y is not None else {}

        if (
            x is not None
            and y is not None
            and isinstance(hit_after, dict)
            and not bool(hit_after.get("has_interactive_ancestor", False))
        ):
            fallback = await self._page.evaluate(
                """([x, y]) => {
                  const el = document.elementFromPoint(Number(x || 0), Number(y || 0));
                  if (!el) return { clicked: false, hit_after: {} };
                  const nearest = el.closest('a,button,input,textarea,select,[role="button"],[role="link"]');
                  let clicked = false;
                  try {
                    if (nearest && typeof nearest.click === 'function') {
                      nearest.click();
                      clicked = true;
                    } else if (typeof el.click === 'function') {
                      el.click();
                      clicked = true;
                    }
                  } catch (_) {}
                  const after = document.elementFromPoint(Number(x || 0), Number(y || 0));
                  const afterInteractive = after ? after.closest('a,button,input,textarea,select,[role="button"],[role="link"]') : null;
                  const text = after ? String((after.innerText || after.textContent || '')).trim().slice(0, 160) : '';
                  return {
                    clicked,
                    hit_after: {
                      top_tag: after ? String(after.tagName || '').toLowerCase() : '',
                      top_text: text,
                      has_interactive_ancestor: !!afterInteractive,
                      interactive_tag: afterInteractive ? String(afterInteractive.tagName || '').toLowerCase() : '',
                    },
                  };
                }""",
                [float(x or 0), float(y or 0)],
            )
            if isinstance(fallback, dict):
                fallback_clicked = bool(fallback.get("clicked", False))
                fallback_hit = fallback.get("hit_after") if isinstance(fallback.get("hit_after"), dict) else {}
                if fallback_hit:
                    hit_after = fallback_hit
                if fallback_clicked:
                    delivered = True

        return self._success_response(
            action="click",
            elapsed=time.time() - t0,
            result_data={
                "kind": "click_action_receipt_v1",
                "delivered": bool(delivered),
                "hit_after": hit_after if isinstance(hit_after, dict) else {},
                "fallback_clicked": bool(fallback_clicked),
            },
        )

    async def type_text(
        self,
        text: str,
        x: Optional[float] = None,
        y: Optional[float] = None,
        selector: str = "",
        press_enter: bool = False,
        focus_before_type: bool = True,
        clear_existing: bool = True,
    ) -> ToonResponse:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return self._error_response("type", "No MCP adapter for type_text")
            t0 = time.time()
            await self._mcp_adapter.type_text(text=text, selector=selector, press_enter=press_enter)
            return self._success_response(
                action="type",
                elapsed=time.time() - t0,
                result_data={
                    "kind": "type_action_receipt_v1",
                    "text_len": len(str(text or "")),
                    "enter_dispatched": bool(press_enter),
                },
            )
        if not self._page:
            return self._error_response("type", "No page for type_text")
        t0 = time.time()

        if selector:
            locator = self._page.locator(selector).first
            if clear_existing:
                await locator.fill("")
            if text:
                await locator.type(str(text), delay=20 if self.humanize_input_enabled else 0)
            if press_enter:
                await locator.press("Enter")
        else:
            cx = float(x if x is not None else 0)
            cy = float(y if y is not None else 0)
            if focus_before_type:
                await self._page.mouse.click(cx, cy)
            if clear_existing:
                try:
                    mod = "Meta" if os.name == "posix" else "Control"
                    await self._page.keyboard.press(f"{mod}+A")
                    await self._page.keyboard.press("Backspace")
                except Exception:
                    pass
            if text:
                await self._page.keyboard.type(str(text), delay=20 if self.humanize_input_enabled else 0)
            if press_enter:
                await self._page.keyboard.press("Enter")

        return self._success_response(
            action="type",
            elapsed=time.time() - t0,
            result_data={
                "kind": "type_action_receipt_v1",
                "text_len": len(str(text or "")),
                "enter_dispatched": bool(press_enter),
            },
        )

    async def press_key(self, key: str, modifiers: Optional[List[str]] = None) -> Dict[str, Any]:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return {"accepted": False, "reason": "no_mcp_adapter"}
            await self._mcp_adapter.press_key(str(key or "Enter"), modifiers=modifiers)
            mods = [str(m).strip() for m in (modifiers or []) if str(m).strip()]
            return {"accepted": True, "key": str(key or "Enter"), "modifiers": mods, "ts": datetime.utcnow().isoformat()}
        if not self._page:
            return {"accepted": False, "reason": "no_page"}
        mods = [str(m).strip() for m in (modifiers or []) if str(m).strip()]
        combo = "+".join(mods + [str(key or "Enter")]) if mods else str(key or "Enter")
        await self._page.keyboard.press(combo)
        return {"accepted": True, "key": str(key or "Enter"), "modifiers": mods, "ts": datetime.utcnow().isoformat()}

    async def scroll_page(self, pixels: int) -> Dict[str, Any]:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return {"delivered": False, "delta_y": 0}
            out = await self._mcp_adapter.scroll_page(int(pixels or 0))
            payload = PlaywrightMCPAdapter._coerce_result_payload(out)
            delta = int(payload.get("delta_y", int(pixels or 0)) or int(pixels or 0))
            return {"kind": "scroll_action_receipt_v1", "delivered": True, "delta_y": delta}
        if not self._page:
            return {"delivered": False, "delta_y": 0}
        delta = int(pixels or 0)
        await self._page.evaluate("(dy) => window.scrollBy(0, dy)", delta)
        return {"kind": "scroll_action_receipt_v1", "delivered": True, "delta_y": delta}

    async def blur_active_editable(self) -> bool:
        if self._transport_mode_effective == "mcp":
            if self._mcp_adapter is None:
                return False
            return await self._mcp_adapter.blur_active_editable()
        if not self._page:
            return False
        try:
            return bool(
                await self._page.evaluate(
                    """() => {
                      const ae = document.activeElement;
                      if (!ae) return false;
                      const tag = (ae.tagName || '').toLowerCase();
                      const editable = tag === 'input' || tag === 'textarea' || ae.isContentEditable;
                      if (!editable) return false;
                      ae.blur();
                      return true;
                    }"""
                )
            )
        except Exception:
            return False

    async def wait_after_action(self, pre_action_focus: Dict[str, Any], action: str) -> None:
        _ = pre_action_focus
        _ = action
        await self._wait_for_load()
        await asyncio.sleep(0.2)

    def _success_response(self, action: str, elapsed: float, message: str = "", result_data: Optional[Dict[str, Any]] = None) -> ToonResponse:
        return ToonResponse(
            command_id=f"pw_{action}_{int(time.time() * 1000)}",
            component="runtime",
            action=action,
            trace_id=self._trace_id,
            step_id=str(self._step_context.get("step_id") or "runtime"),
            status="success",
            execution_time=float(max(0.01, elapsed)),
            message=message or None,
            result_data=result_data or {},
        )

    def _error_response(self, action: str, error: str) -> ToonResponse:
        return ToonResponse(
            command_id=f"pw_{action}_err_{int(time.time() * 1000)}",
            component="runtime",
            action=action,
            trace_id=self._trace_id,
            step_id=str(self._step_context.get("step_id") or "runtime"),
            status="error",
            execution_time=0.01,
            error_details=str(error or "runtime_error"),
        )
