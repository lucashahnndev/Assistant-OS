from __future__ import annotations

import json
import asyncio
import os
import tempfile
import shlex
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger("aosd.capabilities.browser_control.playwright_mcp_adapter")


class PlaywrightMCPAdapter:
    """Thin MCP transport adapter for Playwright-compatible browser tools."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_s: float = 15.0,
        invoker: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        server_command: str = "",
        server_env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.endpoint = str(endpoint or "").strip()
        self.timeout_s = float(max(1.0, timeout_s))
        self._invoker = invoker
        self.calls_total = 0
        self._jsonrpc_id = 0
        self._mcp_session_id: str = ""
        self._mcp_initialized = False
        self._client: Optional[httpx.AsyncClient] = None
        self._server_command = str(server_command or "").strip()
        self._server_env = dict(server_env or {})
        self._use_stdio = bool(self.endpoint.lower().startswith("stdio"))
        self._stdio_proc: Optional[asyncio.subprocess.Process] = None
        self._stdio_reader_task: Optional[asyncio.Task] = None
        self._stdio_stderr_task: Optional[asyncio.Task] = None
        self._stdio_lock: Optional[asyncio.Lock] = None
        self._pending: Dict[int, asyncio.Future] = {}

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        proc = self._stdio_proc
        self._stdio_proc = None
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=4)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        for task in (self._stdio_reader_task, self._stdio_stderr_task):
            if task is not None:
                task.cancel()
        self._stdio_reader_task = None
        self._stdio_stderr_task = None
        self._pending.clear()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s, trust_env=False)
        return self._client

    async def _ensure_stdio_process(self) -> None:
        if self._stdio_proc is not None:
            return
        if not self._server_command:
            raise RuntimeError("Missing MCP server command for stdio transport")
        try:
            args = shlex.split(self._server_command)
        except Exception as e:
            raise RuntimeError(f"Invalid MCP server command: {e}") from e
        if not args:
            raise RuntimeError("Invalid MCP server command (empty)")
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._server_env or None,
        )
        self._stdio_proc = proc
        self._stdio_lock = asyncio.Lock()
        self._stdio_reader_task = asyncio.create_task(self._stdio_reader())
        self._stdio_stderr_task = asyncio.create_task(self._stderr_reader())

    async def _stderr_reader(self) -> None:
        proc = self._stdio_proc
        if not proc or not proc.stderr:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="ignore").rstrip()
                except Exception:
                    text = str(line)
                if text:
                    logger.debug("MCP stdio stderr | %s", text)
        except asyncio.CancelledError:
            pass

    async def _stdio_reader(self) -> None:
        proc = self._stdio_proc
        if not proc or not proc.stdout:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    text = line.decode("utf-8", errors="ignore").strip()
                except Exception:
                    text = ""
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except Exception:
                    logger.debug("MCP stdio invalid JSON: %s", text[:200])
                    continue
                if isinstance(payload, dict) and "id" in payload:
                    msg_id = payload.get("id")
                    fut = self._pending.pop(msg_id, None)
                    if fut and not fut.done():
                        fut.set_result(payload)
                else:
                    # Notifications are ignored for now.
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            # Fail any pending calls if the server dies.
            for _id, fut in list(self._pending.items()):
                if fut and not fut.done():
                    fut.set_exception(RuntimeError("MCP stdio server closed"))
            self._pending.clear()

    async def _stdio_send(self, payload: Dict[str, Any]) -> None:
        await self._ensure_stdio_process()
        if not self._stdio_proc or not self._stdio_proc.stdin:
            raise RuntimeError("MCP stdio stdin unavailable")
        text = json.dumps(payload, separators=(",", ":"))
        if "\n" in text:
            text = text.replace("\n", "\\n")
        data = (text + "\n").encode("utf-8")
        async with self._stdio_lock:
            self._stdio_proc.stdin.write(data)
            await self._stdio_proc.stdin.drain()

    async def _stdio_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = payload.get("id")
        if msg_id is None:
            raise RuntimeError("MCP stdio request missing id")
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[msg_id] = fut
        await self._stdio_send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=self.timeout_s)
        finally:
            self._pending.pop(msg_id, None)

    async def _ensure_stdio_initialized(self) -> None:
        if self._mcp_initialized:
            return
        logger.debug("MCP stdio initialize start")
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_jsonrpc_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "assistant-os", "version": "1.0"},
            },
        }
        init_resp = await self._stdio_request(init_payload)
        if not isinstance(init_resp, dict):
            raise RuntimeError("Invalid MCP stdio initialize response payload")
        if isinstance(init_resp.get("error"), dict):
            message = str(init_resp["error"].get("message", "MCP initialize error"))
            raise RuntimeError(message)
        notify_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        await self._stdio_send(notify_payload)
        self._mcp_initialized = True
        logger.debug("MCP stdio initialize ok")

    async def _call_tool_stdio(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_stdio_initialized()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_jsonrpc_id(),
            "method": "tools/call",
            "params": {"name": str(name or ""), "arguments": dict(args or {})},
        }
        data = await self._stdio_request(payload)
        if not isinstance(data, dict):
            raise RuntimeError("Invalid MCP stdio response payload")
        if isinstance(data.get("error"), dict):
            message = str(data["error"].get("message", "MCP stdio error"))
            raise RuntimeError(message)
        return {"result": data.get("result")}

    async def get_page_info(self) -> Dict[str, Any]:
        # Preferred path for MCP servers exposing an evaluate/run-code tool.
        result = await self._call_tool_preferred(
            ["browser_run_code", "browser_evaluate"],
            {
                "code": (
                    "async (page) => ({ url: String(page.url()||''), "
                    "title: String(await page.title()), "
                    "viewport: page.viewportSize ? page.viewportSize() : {w:0,h:0} })"
                ),
                "function": "() => ({ url: String(location.href||''), title: String(document.title||''), viewport: {w: Number(window.innerWidth||0), h: Number(window.innerHeight||0)} })",
            },
        )
        payload = self._coerce_result_payload(result)
        viewport = payload.get("viewport") if isinstance(payload.get("viewport"), dict) else {}
        return {
            "url": str(payload.get("url", "") or ""),
            "title": str(payload.get("title", "") or ""),
            "viewport": {
                "w": int(viewport.get("w", viewport.get("width", 0)) or 0),
                "h": int(viewport.get("h", viewport.get("height", 0)) or 0),
            },
        }

    async def navigate(self, url: str) -> Dict[str, Any]:
        return await self._call_tool_preferred(
            ["browser_navigate"],
            {"url": str(url or "about:blank")},
        )

    async def click(self, *, x: Optional[float] = None, y: Optional[float] = None, selector: str = "") -> Dict[str, Any]:
        if selector:
            return await self._call_tool_preferred(
                ["browser_click"],
                {"element": f"selector:{selector}", "ref": selector},
            )
        return await self._call_tool_preferred(
            ["browser_run_code", "browser_click"],
            {
                "code": (
                    "async (page) => page.evaluate(([x, y]) => {"
                    "  const el = document.elementFromPoint(Number(x || 0), Number(y || 0));"
                    "  if (!el) return { clicked: false, fallback_clicked: false, hit_after: {} };"
                    "  const nearest = el.closest('a,button,input,textarea,select,[role=\"button\"],[role=\"link\"]');"
                    "  let clicked = false;"
                    "  let fallbackClicked = false;"
                    "  try {"
                    "    if (nearest && typeof nearest.click === 'function') { nearest.click(); clicked = true; fallbackClicked = true; }"
                    "    else if (typeof el.click === 'function') { el.click(); clicked = true; }"
                    "  } catch (_) {}"
                    "  const after = document.elementFromPoint(Number(x || 0), Number(y || 0));"
                    "  const afterInteractive = after ? after.closest('a,button,input,textarea,select,[role=\"button\"],[role=\"link\"]') : null;"
                    "  const topText = after ? String((after.innerText || after.textContent || '')).trim().slice(0, 160) : '';"
                    "  return {"
                    "    clicked,"
                    "    fallback_clicked: fallbackClicked,"
                    "    hit_after: {"
                    "      top_tag: after ? String(after.tagName || '').toLowerCase() : '',"
                    "      top_text: topText,"
                    "      has_interactive_ancestor: !!afterInteractive,"
                    "      interactive_tag: afterInteractive ? String(afterInteractive.tagName || '').toLowerCase() : ''"
                    "    }"
                    "  };"
                    "}, [" + str(float(x or 0)) + ", " + str(float(y or 0)) + "])"
                ),
                "element": f"coords:{float(x or 0)},{float(y or 0)}",
                "ref": "viewport",
            },
        )

    async def type_text(self, *, text: str, selector: str = "", press_enter: bool = False) -> Dict[str, Any]:
        if selector:
            return await self._call_tool_preferred(
                ["browser_type", "browser_fill_form"],
                {
                    "element": f"selector:{selector}",
                    "ref": selector,
                    "text": str(text or ""),
                    "submit": bool(press_enter),
                    "fields": [{"name": selector, "ref": selector, "type": "textbox", "value": str(text or "")}],
                },
            )
        out = await self._call_tool_preferred(
            ["browser_type", "browser_run_code"],
            {
                "ref": "active-element",
                "text": str(text or ""),
                "submit": bool(press_enter),
                "code": (
                    "async (page) => {"
                    "  const ae = await page.evaluateHandle(() => document.activeElement);"
                    "  if (ae) { await ae.asElement()?.type(" + json.dumps(str(text or "")) + "); }"
                    "  if (" + ("true" if press_enter else "false") + ") { await page.keyboard.press('Enter'); }"
                    "  return {typed:true};"
                    "}"
                ),
            },
        )
        return out

    async def press_key(self, key: str, modifiers: Optional[List[str]] = None) -> Dict[str, Any]:
        mods = [str(m).strip() for m in (modifiers or []) if str(m).strip()]
        combo = "+".join(mods + [str(key or "Enter")]) if mods else str(key or "Enter")
        return await self._call_tool_preferred(
            ["browser_press_key"],
            {"key": combo},
        )

    async def scroll_page(self, pixels: int) -> Dict[str, Any]:
        return await self._call_tool_preferred(
            ["browser_run_code"],
            {"code": f"async (page) => {{ await page.evaluate((dy)=>window.scrollBy(0,dy), {int(pixels)}); return {{delta_y:{int(pixels)}}}; }}"},
        )

    async def blur_active_editable(self) -> bool:
        out = await self._call_tool_preferred(
            ["browser_run_code"],
            {
                "code": (
                    "async (page) => page.evaluate(() => {"
                    "  const ae = document.activeElement;"
                    "  if (!ae) return false;"
                    "  const tag = (ae.tagName || '').toLowerCase();"
                    "  const editable = tag === 'input' || tag === 'textarea' || ae.isContentEditable;"
                    "  if (!editable) return false;"
                    "  ae.blur(); return true;"
                    "})"
                )
            },
        )
        payload = self._coerce_result_payload(out)
        return bool(payload.get("result", payload.get("blurred", False)))

    async def capture_screenshot_to_file(self, *, image_format: str = "png") -> str:
        suffix = ".jpg" if str(image_format or "png").lower() == "jpeg" else ".png"
        fd, path = tempfile.mkstemp(prefix="aosd_mcp_", suffix=suffix)
        os.close(fd)
        await self._call_tool_preferred(
            ["browser_take_screenshot"],
            {"type": "jpeg" if suffix == ".jpg" else "png", "filename": path},
        )
        return path

    async def capture_screenshot_bytes(self) -> bytes:
        path = await self.capture_screenshot_to_file(image_format="jpeg")
        try:
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    async def list_tabs(self) -> Dict[str, Any]:
        out = await self._call_tool_preferred(["browser_tabs"], {"action": "list"})
        payload = self._coerce_result_payload(out)
        tabs = self._coerce_tabs_payload(payload)
        active_index = int(payload.get("active_index", 0) or 0) if isinstance(payload, dict) else 0
        if tabs:
            current_tabs = [t for t in tabs if isinstance(t, dict) and bool(t.get("current"))]
            if current_tabs:
                try:
                    active_index = int(current_tabs[0].get("index", active_index) or active_index)
                except Exception:
                    pass
        if active_index < 0:
            active_index = 0
        if tabs and active_index >= len(tabs):
            active_index = len(tabs) - 1
        return {"tabs": tabs, "active_index": active_index}

    async def select_tab(self, index: int) -> Dict[str, Any]:
        idx = int(index or 0)
        out = await self._call_tool_preferred(["browser_tabs"], {"action": "select", "index": idx})
        payload = self._coerce_result_payload(out)
        return payload if isinstance(payload, dict) else {}

    async def create_tab(self, url: str = "about:blank") -> Dict[str, Any]:
        target_url = str(url or "about:blank")
        try:
            out = await self._call_tool("browser_tabs", {"action": "new", "url": target_url})
            payload = self._coerce_result_payload(out)
            idx = int(payload.get("index", -1) or -1) if isinstance(payload, dict) else -1
            if idx < 0:
                tabs_meta = await self.list_tabs()
                idx = int(tabs_meta.get("active_index", 0) or 0)
            if idx < 0:
                idx = 0
            return {"index": idx}
        except Exception:
            # Legacy compatibility path for older adapters/servers that still expose
            # a create-then-navigate flow instead of browser_tabs action=new.
            out = await self._call_tool("browser_tabs", {"action": "create"})
            payload = self._coerce_result_payload(out)
            idx = int(payload.get("index", 0) or 0) if isinstance(payload, dict) else 0
            if idx < 0:
                idx = 0
            await self.select_tab(idx)
            await self.navigate(target_url)
            return {"index": idx}

    async def get_skeletal_dom(self) -> Dict[str, Any]:
        # Primary path: collect a lightweight, planner-compatible DOM slice via MCP run_code/evaluate.
        result = await self._call_tool_preferred(
            ["browser_run_code", "browser_evaluate"],
            {
                "code": (
                    "async (page) => page.evaluate(() => {"
                    "  const vw = Number(window.innerWidth || 1280);"
                    "  const vh = Number(window.innerHeight || 720);"
                    "  const all = Array.from(document.querySelectorAll("
                    "    'a,button,input,textarea,select,[role],h1,h2,h3,p,span,div'"
                    "  ));"
                    "  const nodes = [];"
                    "  const markers = [];"
                    "  let idx = 0;"
                    "  for (const el of all.slice(0, 260)) {"
                    "    const rect = el.getBoundingClientRect();"
                    "    const text = String("
                    "      (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '')"
                    "    ).trim().slice(0, 140);"
                    "    const role = String(el.getAttribute('role') || '').trim();"
                    "    const tag = String(el.tagName || '').toLowerCase();"
                    "    const inViewport = rect.width > 1 && rect.height > 1 && "
                    "      rect.bottom >= 0 && rect.right >= 0 && rect.top <= vh && rect.left <= vw;"
                    "    const node = {"
                    "      id: `pw_node_${idx++}`,"
                    "      tag,"
                    "      role,"
                    "      text,"
                    "      inViewport,"
                    "      bbox: {"
                    "        x: Math.max(0, Number(rect.left || 0)),"
                    "        y: Math.max(0, Number(rect.top || 0)),"
                    "        w: Math.max(0, Number(rect.width || 0)),"
                    "        h: Math.max(0, Number(rect.height || 0))"
                    "      }"
                    "    };"
                    "    nodes.push(node);"
                    "    if ((tag === 'h1' || tag === 'h2' || role === 'heading') && text) {"
                    "      markers.push({ text, tag, role, id: `mk_${markers.length + 1}`, kind: 'heading' });"
                    "    }"
                    "  }"
                    "  const ae = document.activeElement;"
                    "  const focus = ae ? {"
                    "    tag: String(ae.tagName || '').toLowerCase(),"
                    "    id: String(ae.id || ''),"
                    "    role: ae.getAttribute ? String(ae.getAttribute('role') || '') : ''"
                    "  } : {};"
                    "  return {"
                    "    nodes,"
                    "    markers,"
                    "    focus,"
                    "    total_count: Number(nodes.length || 0),"
                    "    viewport_count: Number(nodes.filter(n => !!n.inViewport).length || 0)"
                    "  };"
                    "})"
                ),
                "function": (
                    "() => {"
                    "  const vw = Number(window.innerWidth || 1280);"
                    "  const vh = Number(window.innerHeight || 720);"
                    "  const all = Array.from(document.querySelectorAll('a,button,input,textarea,select,[role],h1,h2,h3,p,span,div'));"
                    "  const nodes = [];"
                    "  const markers = [];"
                    "  let idx = 0;"
                    "  for (const el of all.slice(0, 260)) {"
                    "    const rect = el.getBoundingClientRect();"
                    "    const text = String((el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '')).trim().slice(0, 140);"
                    "    const role = String(el.getAttribute('role') || '').trim();"
                    "    const tag = String(el.tagName || '').toLowerCase();"
                    "    const inViewport = rect.width > 1 && rect.height > 1 && rect.bottom >= 0 && rect.right >= 0 && rect.top <= vh && rect.left <= vw;"
                    "    nodes.push({"
                    "      id: `pw_node_${idx++}`, tag, role, text, inViewport,"
                    "      bbox: { x: Math.max(0, Number(rect.left||0)), y: Math.max(0, Number(rect.top||0)), w: Math.max(0, Number(rect.width||0)), h: Math.max(0, Number(rect.height||0)) }"
                    "    });"
                    "    if ((tag === 'h1' || tag === 'h2' || role === 'heading') && text) markers.push({ text, tag, role, id: `mk_${markers.length + 1}`, kind: 'heading' });"
                    "  }"
                    "  const ae = document.activeElement;"
                    "  const focus = ae ? { tag: String(ae.tagName || '').toLowerCase(), id: String(ae.id || ''), role: ae.getAttribute ? String(ae.getAttribute('role') || '') : '' } : {};"
                    "  return { nodes, markers, focus, total_count: Number(nodes.length || 0), viewport_count: Number(nodes.filter(n => !!n.inViewport).length || 0) };"
                    "}"
                ),
            },
        )
        payload = self._coerce_result_payload(result)
        nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        markers = payload.get("markers") if isinstance(payload.get("markers"), list) else []
        focus = payload.get("focus") if isinstance(payload.get("focus"), dict) else {}
        total_count = int(payload.get("total_count", len(nodes)) or len(nodes))
        viewport_count = int(payload.get("viewport_count", 0) or 0)
        if viewport_count <= 0 and nodes:
            viewport_count = sum(1 for n in nodes if isinstance(n, dict) and bool(n.get("inViewport")))
        return {
            "nodes": nodes,
            "markers": markers,
            "focus": focus,
            "total_count": total_count,
            "viewport_count": viewport_count,
        }

    async def _call_tool_preferred(self, tool_names: List[str], args: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for name in [str(t).strip() for t in tool_names if str(t).strip()]:
            try:
                return await self._call_tool(name, args)
            except Exception as e:
                last_error = e
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("No MCP tool names provided")

    async def _call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self.calls_total += 1
        if self._invoker is not None:
            out = await self._invoker(name, dict(args or {}))
            return out if isinstance(out, dict) else {"result": out}

        if self._use_stdio:
            logger.debug("MCP stdio tool call | tool=%s", name)
            return await self._call_tool_stdio(name, args)

        if not self.endpoint:
            raise RuntimeError("Missing MCP endpoint")

        # Strict MCP mode: prefer streamable MCP JSON-RPC endpoint (/mcp).
        # Legacy /tools/call is only used when explicitly configured.
        last_error: Optional[Exception] = None
        for endpoint in self._endpoint_candidates():
            try:
                logger.debug(
                    "MCP tool call start | tool=%s endpoint=%s session_id=%s initialized=%s",
                    name,
                    endpoint,
                    self._mcp_session_id or "",
                    self._mcp_initialized,
                )
                if endpoint.endswith("/mcp"):
                    return await self._call_tool_mcp_jsonrpc(endpoint, name, args)
                if endpoint.endswith("/tools/call"):
                    return await self._call_tool_mcp_jsonrpc(endpoint, name, args)
                return await self._call_tool_legacy(endpoint, name, args)
            except Exception as e:
                last_error = e
                logger.debug("MCP call failed for endpoint=%s tool=%s: %s", endpoint, name, e)
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("No valid MCP endpoint candidates")

    def _endpoint_candidates(self) -> List[str]:
        raw = self._canonicalize_endpoint(str(self.endpoint or "").strip()).rstrip("/")
        if not raw:
            return []
        parsed = urlparse(raw)
        if parsed.path.endswith("/mcp"):
            return [raw]
        if parsed.path.endswith("/tools/call"):
            return [raw]
        return [raw + "/mcp"]

    @staticmethod
    def _canonicalize_endpoint(raw_endpoint: str) -> str:
        raw = str(raw_endpoint or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").strip().lower()
        if host == "127.0.0.1":
            # playwright-mcp HTTP transport rejects 127.0.0.1 Host and requires localhost.
            netloc = parsed.netloc
            if parsed.username:
                auth = parsed.username
                if parsed.password:
                    auth += f":{parsed.password}"
                auth += "@"
            else:
                auth = ""
            port = f":{parsed.port}" if parsed.port else ""
            netloc = f"{auth}localhost{port}"
            parsed = parsed._replace(netloc=netloc)
            return urlunparse(parsed)
        return raw

    def _next_jsonrpc_id(self) -> int:
        self._jsonrpc_id += 1
        return int(self._jsonrpc_id)

    async def _call_tool_mcp_jsonrpc(self, endpoint: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        await self._ensure_mcp_initialized(endpoint)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_jsonrpc_id(),
            "method": "tools/call",
            "params": {
                "name": str(name or ""),
                "arguments": dict(args or {}),
            },
        }
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if self._mcp_session_id:
            headers["mcp-session-id"] = self._mcp_session_id
        client = self._get_client()
        resp = await client.post(endpoint, json=payload, headers=headers)
        logger.debug(
            "MCP tool call response | tool=%s status=%s session_id=%s",
            name,
            resp.status_code,
            self._mcp_session_id or "",
        )
        if resp.status_code >= 400:
            snippet = resp.text[:500] if isinstance(resp.text, str) else str(resp.text)
            logger.debug(
                "MCP tool call error payload | tool=%s status=%s session_id=%s headers=%s body=%s",
                name,
                resp.status_code,
                self._mcp_session_id or "",
                dict(resp.headers),
                snippet,
            )
        # Session may expire in server side; retry once with a new initialize handshake.
        # Some MCP servers can also return 404 for unknown/expired session handles.
        if resp.status_code in {401, 403, 404, 409}:
            self._mcp_initialized = False
            self._mcp_session_id = ""
            await self._ensure_mcp_initialized(endpoint)
            if self._mcp_session_id:
                headers["mcp-session-id"] = self._mcp_session_id
            resp = await client.post(endpoint, json=payload, headers=headers)
            logger.debug(
                "MCP tool call retry | tool=%s status=%s session_id=%s",
                name,
                resp.status_code,
                self._mcp_session_id or "",
            )
            if resp.status_code >= 400:
                snippet = resp.text[:500] if isinstance(resp.text, str) else str(resp.text)
                logger.debug(
                    "MCP tool call retry error payload | tool=%s status=%s session_id=%s headers=%s body=%s",
                    name,
                    resp.status_code,
                    self._mcp_session_id or "",
                    dict(resp.headers),
                    snippet,
                )
        resp.raise_for_status()
        data = self._decode_mcp_payload(resp.text)
        if not isinstance(data, dict):
            raise RuntimeError("Invalid MCP JSON-RPC response payload")
        if isinstance(data.get("error"), dict):
            message = str(data["error"].get("message", "MCP JSON-RPC error"))
            raise RuntimeError(message)
        return {"result": data.get("result")}

    async def _ensure_mcp_initialized(self, endpoint: str) -> None:
        if self._mcp_initialized:
            return
        logger.debug("MCP initialize start | endpoint=%s", endpoint)
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_jsonrpc_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "assistant-os", "version": "1.0"},
            },
        }
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        client = self._get_client()
        resp = await client.post(endpoint, json=init_payload, headers=headers)
        if resp.status_code in {404, 405}:
            raise RuntimeError(f"MCP JSON-RPC endpoint unavailable: {endpoint}")
        resp.raise_for_status()
        data = self._decode_mcp_payload(resp.text)
        self._mcp_session_id = (
            str(resp.headers.get("mcp-session-id", "") or resp.headers.get("Mcp-Session-Id", "") or "").strip()
        )
        notify_headers = dict(headers)
        if self._mcp_session_id:
            notify_headers["mcp-session-id"] = self._mcp_session_id
        notify_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        notify_resp = await client.post(endpoint, json=notify_payload, headers=notify_headers)
        notify_resp.raise_for_status()
        logger.debug("MCP initialize ok | endpoint=%s session_id=%s", endpoint, self._mcp_session_id or "")
        if not isinstance(data, dict):
            raise RuntimeError("Invalid MCP initialize response payload")
        if isinstance(data.get("error"), dict):
            message = str(data["error"].get("message", "MCP initialize error"))
            raise RuntimeError(message)
        self._mcp_initialized = True

    async def _call_tool_legacy(self, endpoint: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"name": str(name or ""), "arguments": dict(args or {})}
        client = self._get_client()
        resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = self._decode_mcp_payload(resp.text)
        if not isinstance(data, dict):
            raise RuntimeError("Invalid MCP legacy response payload")
        if data.get("error"):
            raise RuntimeError(str(data.get("error")))
        return data

    @staticmethod
    def _decode_mcp_payload(raw_text: str) -> Dict[str, Any]:
        raw = str(raw_text or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass

        # SSE frame fallback:
        # event: message
        # data: {"jsonrpc":"2.0", ...}
        data_lines: List[str] = []
        for line in raw.splitlines():
            item = line.strip()
            if not item.startswith("data:"):
                continue
            data_lines.append(item[len("data:") :].strip())
        if not data_lines:
            raise RuntimeError("Invalid MCP response payload (not JSON/SSE)")
        joined = "\n".join([d for d in data_lines if d])
        try:
            parsed = json.loads(joined)
        except Exception as e:
            raise RuntimeError(f"Invalid MCP SSE payload: {e}") from e
        if not isinstance(parsed, dict):
            raise RuntimeError("Invalid MCP SSE payload object")
        return parsed

    @staticmethod
    def _coerce_result_payload(result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        if isinstance(result.get("result"), dict):
            payload = dict(result.get("result") or {})
            # MCP servers may wrap structured output in `content[].text` markdown.
            text_blocks = PlaywrightMCPAdapter._extract_text_blocks(payload)
            for text in text_blocks:
                parsed = PlaywrightMCPAdapter._extract_json_from_text(text)
                if isinstance(parsed, dict):
                    return parsed
                if isinstance(parsed, list):
                    return {"items": parsed}
            return payload
        if isinstance(result.get("output"), dict):
            return dict(result.get("output") or {})
        return dict(result)

    @staticmethod
    def _coerce_tabs_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        tabs_raw = payload.get("tabs")
        if isinstance(tabs_raw, list):
            return [t for t in tabs_raw if isinstance(t, dict)]
        if isinstance(payload.get("result"), list):
            return [t for t in payload.get("result") if isinstance(t, dict)]
        if isinstance(payload.get("items"), list):
            return [t for t in payload.get("items") if isinstance(t, dict)]
        # Textual MCP payload fallback:
        # "### Result\n- 0: (current) [Title](url)"
        tabs: List[Dict[str, Any]] = []
        for text in PlaywrightMCPAdapter._extract_text_blocks(payload):
            for line in str(text or "").splitlines():
                item = line.strip()
                if not item.startswith("- "):
                    continue
                m = re.match(r"^-\s*(\d+)\s*:\s*(\(current\)\s*)?\[(.*?)\]\((.*?)\)\s*$", item)
                if not m:
                    continue
                idx = int(m.group(1))
                is_current = bool(m.group(2))
                title = str(m.group(3) or "")
                url = str(m.group(4) or "")
                tabs.append({"index": idx, "title": title, "url": url, "current": is_current})
        if tabs:
            tabs.sort(key=lambda t: int(t.get("index", 0) or 0))
            return tabs
        return []

    @staticmethod
    def _extract_text_blocks(payload: Dict[str, Any]) -> List[str]:
        if not isinstance(payload, dict):
            return []
        content = payload.get("content")
        if not isinstance(content, list):
            return []
        out: List[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type", "")).strip().lower() != "text":
                continue
            text = str(item.get("text", "") or "")
            if text:
                out.append(text)
        return out

    @staticmethod
    def _extract_json_from_text(text: str) -> Any:
        raw = str(text or "")
        if not raw:
            return None
        decoder = json.JSONDecoder()
        for i, ch in enumerate(raw):
            if ch not in "{[":
                continue
            try:
                parsed, _end = decoder.raw_decode(raw[i:])
                return parsed
            except Exception:
                continue
        return None
