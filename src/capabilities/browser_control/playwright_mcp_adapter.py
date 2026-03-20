from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx


class PlaywrightMCPAdapter:
    """Thin MCP transport adapter for Playwright-compatible browser tools."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_s: float = 15.0,
        invoker: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
    ) -> None:
        self.endpoint = str(endpoint or "").strip()
        self.timeout_s = float(max(1.0, timeout_s))
        self._invoker = invoker
        self.calls_total = 0

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
                "code": f"async (page) => {{ await page.mouse.click({float(x or 0)}, {float(y or 0)}); return {{clicked:true}}; }}",
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
        out = await self._call_tool_preferred(["browser_tabs"], {"action": "create"})
        payload = self._coerce_result_payload(out)
        idx = int(payload.get("index", 0) or 0) if isinstance(payload, dict) else 0
        if idx < 0:
            idx = 0
        # Ensure the new tab becomes active before navigation.
        await self.select_tab(idx)
        await self.navigate(str(url or "about:blank"))
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

        if not self.endpoint:
            raise RuntimeError("Missing MCP endpoint")

        payload = {"name": str(name or ""), "arguments": dict(args or {})}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(f"{self.endpoint.rstrip('/')}/tools/call", json=payload)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid MCP response payload")
        if data.get("error"):
            raise RuntimeError(str(data.get("error")))
        return data

    @staticmethod
    def _coerce_result_payload(result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        if isinstance(result.get("result"), dict):
            return dict(result.get("result") or {})
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
        return []
