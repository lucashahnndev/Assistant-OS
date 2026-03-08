import os
import json
import shutil
import tempfile
import subprocess
import asyncio
import logging
import time
import base64
import socket
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Literal
from pydantic import BaseModel

from .schemas import ToonResponse, EvidencePack, BBox, BrowserAction

logger = logging.getLogger("aosd.skills.browser_control.runtime")

class BrowserRuntime:
    def __init__(self, 
                 chrome_path: str = "/usr/bin/google-chrome",
                 base_profile_path: str = "src/skills/browser_control/profiles/fixed_base",
                 overlay_profile_parent: str = "src/skills/browser_control/profiles/session_overlay",
                 remote_debugging_port: Optional[int] = None,
                 headless: bool = False,
                 muted: bool = False,
                 app_mode: bool = False,
                 launch_url: str = "about:blank"):
        self.chrome_path = chrome_path
        self.base_profile_path = os.path.abspath(base_profile_path)
        self.overlay_profile_parent = os.path.abspath(overlay_profile_parent)
        self.remote_debugging_port = remote_debugging_port
        self.headless = headless
        self.muted = muted
        self.app_mode = app_mode
        self.launch_url = str(launch_url or "about:blank")
        
        self.session_profile_path: Optional[str] = None
        self.chrome_process: Optional[subprocess.Popen] = None
        self.ws_url: Optional[str] = None
        self.target_id: Optional[str] = None
        self.websocket: Optional[Any] = None
        self._next_id = 1
        self._trace_id = f"trace_{int(time.time())}"
        
        # CDP Domains to enable
        self.enabled_domains = ["Page", "DOM", "Runtime", "Network", "Log"]
        self.console_logs: List[str] = []
        self.network_failures: List[Dict[str, Any]] = []

    @staticmethod
    def _pick_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    async def launch(self):
        """Step 0: Launch Chrome with profile overlay and connect to CDP."""
        logger.info(f"Launching Chrome from {self.chrome_path}")

        if not self.remote_debugging_port or int(self.remote_debugging_port) <= 0:
            self.remote_debugging_port = self._pick_free_port()
        
        # Create session overlay (Copy-on-Write template)
        self.session_profile_path = os.path.join(self.overlay_profile_parent, f"session_{int(time.time())}")
        os.makedirs(self.session_profile_path, exist_ok=True)
        
        if os.path.exists(self.base_profile_path) and os.listdir(self.base_profile_path):
            logger.info(f"Copying base profile from {self.base_profile_path}")
            shutil.copytree(self.base_profile_path, self.session_profile_path, dirs_exist_ok=True)

        args = [
            self.chrome_path,
            f"--remote-debugging-port={self.remote_debugging_port}",
            f"--user-data-dir={self.session_profile_path}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-client-side-phishing-detection",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-dev-shm-usage",
            "--disable-domain-reliability",
            "--disable-extensions",
            "--disable-features=AudioServiceOutOfProcess",
            "--disable-hang-monitor",
            "--disable-ipc-flooding-protection",
            "--disable-notifications",
            "--disable-offer-store-unmasked-wallet-cards",
            "--disable-popup-blocking",
            "--disable-print-preview",
            "--disable-prompt-on-repost",
            "--disable-renderer-backgrounding",
            "--disable-speech-api",
            "--hide-scrollbars",
            "--ignore-gpu-blacklist",
            "--metrics-recording-only",
            "--no-pings",
            "--password-store=basic",
            "--use-mock-keychain",
        ]

        if self.headless:
            args.append("--headless=new")
        if self.muted:
            args.append("--mute-audio")
        if self.app_mode:
            args.append(f"--app={self.launch_url}")
        else:
            args.append(self.launch_url)

        self.chrome_process = subprocess.Popen(args, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        
        # Wait for WS endpoint to be available
        start_time = time.time()
        while time.time() - start_time < 10:
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"http://localhost:{self.remote_debugging_port}/json/version")
                    if resp.status_code == 200:
                        data = resp.json()
                        self.ws_url = data['webSocketDebuggerUrl']
                        logger.info(f"CDP WebSocket resolved: {self.ws_url}")
                        break
            except Exception:
                await asyncio.sleep(0.5)
        
        if not self.ws_url:
            raise RuntimeError("Failed to resolve CDP WebSocket endpoint")

        # Step 0.5: Resolve the first available page target
        # The browser WS URL is for browser-level commands. We need a page target.
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://localhost:{self.remote_debugging_port}/json/list")
            targets = resp.json()
            page_targets = [t for t in targets if t.get("type") == "page"]
            page_target = None
            if self.launch_url and self.launch_url != "about:blank":
                page_target = next((t for t in page_targets if str(t.get("url", "")).startswith(self.launch_url)), None)
            if page_target is None and page_targets:
                page_target = page_targets[-1]
            if page_target and 'webSocketDebuggerUrl' in page_target:
                self.target_id = str(page_target.get("id", "") or "")
                self.ws_url = page_target['webSocketDebuggerUrl']
                logger.info(f"Targeting page WS: {self.ws_url}")

        # Connect and enable domains
        import websockets
        self.websocket = await websockets.connect(self.ws_url, max_size=2**24) # 16MB limit
        for domain in self.enabled_domains:
            await self._call_cdp(f"{domain}.enable")
            
        logger.info("CDP Handshake successful and domains enabled.")

    def get_connection_metadata(self) -> Dict[str, Any]:
        return {
            "debug_port": self.remote_debugging_port,
            "ws_url": self.ws_url,
            "target_id": self.target_id,
            "app_mode": self.app_mode,
            "launch_url": self.launch_url,
        }

    async def attach_to_target(self, target_id: str) -> bool:
        """
        Reattach websocket to a specific page target by CDP target id.
        Returns True when reattached.
        """
        wanted = str(target_id or "").strip()
        if not wanted or not self.remote_debugging_port:
            return False
        if wanted == str(self.target_id or ""):
            return True
        try:
            import httpx
            import websockets
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://localhost:{self.remote_debugging_port}/json/list")
                targets = resp.json() if resp.status_code == 200 else []
            page = next((t for t in targets if str(t.get("id", "")) == wanted and t.get("type") == "page"), None)
            if not page or "webSocketDebuggerUrl" not in page:
                return False

            if self.websocket:
                try:
                    await self.websocket.close()
                except Exception:
                    pass
            self.ws_url = str(page["webSocketDebuggerUrl"])
            self.target_id = wanted
            self.websocket = await websockets.connect(self.ws_url, max_size=2**24)
            for domain in self.enabled_domains:
                await self._call_cdp(f"{domain}.enable")
            return True
        except Exception as e:
            logger.warning(f"Failed to attach to target {wanted}: {e}")
            return False

    async def list_page_targets(self) -> List[Dict[str, Any]]:
        """
        Returns current CDP page targets from /json/list.
        """
        if not self.remote_debugging_port:
            return []
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"http://localhost:{self.remote_debugging_port}/json/list")
                targets = resp.json() if resp.status_code == 200 else []
            return [t for t in targets if isinstance(t, dict) and t.get("type") == "page"]
        except Exception:
            return []

    async def attach_to_any_page(self, preferred_target_ids: Optional[List[str]] = None) -> Optional[str]:
        """
        Fallback attach: tries preferred target ids first, then any available page target.
        Returns the attached target id or None.
        """
        targets = await self.list_page_targets()
        if not targets:
            return None

        preferred = [str(t or "").strip() for t in (preferred_target_ids or []) if str(t or "").strip()]
        ordered: List[str] = []
        ordered.extend(preferred)
        ordered.extend([str(t.get("id") or "") for t in targets if str(t.get("id") or "").strip() not in preferred])

        for target_id in ordered:
            if not target_id:
                continue
            ok = await self.attach_to_target(target_id)
            if ok:
                return target_id
        return None

    async def open_new_tab(self, url: str = "about:blank") -> Optional[str]:
        """
        Opens a new page tab via Chrome remote debugging endpoint and attaches to it.
        Returns target id when successful.
        """
        if not self.remote_debugging_port:
            return None
        target_url = str(url or "about:blank").strip() or "about:blank"
        encoded = urllib.parse.quote(target_url, safe=":/?&=#%")
        created_target = ""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                # Legacy/new endpoint supported by Chrome's remote debugging server.
                resp = await client.get(f"http://localhost:{self.remote_debugging_port}/json/new?{encoded}")
                if resp.status_code in {200, 201}:
                    data = resp.json() if resp.text else {}
                    created_target = str(data.get("id") or "")
        except Exception:
            created_target = ""

        if created_target and await self.attach_to_target(created_target):
            return created_target
        # Fallback: try attach any page, preferring the newly created id if present.
        recovered = await self.attach_to_any_page([created_target] if created_target else None)
        return recovered

    async def _call_cdp(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.websocket:
            raise RuntimeError("Not connected to CDP")
            
        msg_id = self._next_id
        self._next_id += 1
        
        payload = {
            "id": msg_id,
            "method": method,
            "params": params or {}
        }
        
        await self.websocket.send(json.dumps(payload))
        
        # Listen for response with matching ID
        while True:
            try:
                msg = await self.websocket.recv()
                data = json.loads(msg)
                
                # Handle events (simplified for now)
                if "method" in data:
                    self._handle_cdp_event(data)
                    continue
                
                if data.get("id") == msg_id:
                    if "error" in data:
                        raise RuntimeError(f"CDP Error ({method}): {data['error'].get('message')}")
                    return data.get("result")
            except Exception as e:
                import websockets
                if isinstance(e, websockets.ConnectionClosed):
                    raise RuntimeError("CDP connection closed")
                raise

    def _handle_cdp_event(self, data: Dict[str, Any]):
        method = data.get("method")
        params = data.get("params", {})
        
        if method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error":
                self.console_logs.append(f"[{entry.get('source')}] {entry.get('text')}")
        
        elif method == "Network.loadingFailed":
            self.network_failures.append({
                "requestId": params.get("requestId"),
                "errorText": params.get("errorText"),
                "canceled": params.get("canceled")
            })

    async def get_skeletal_dom(self) -> Dict[str, Any]:
        """
        UI Snapshot Generator: Transforms raw DOM into TWO streams:
        1. nodes: Interactive candidates for clicking/typing.
        2. markers: Informational landmarks (titles, headings) for verification.
        """
        js_code = """
        (() => {
            const vH = window.innerHeight;
            const vW = window.innerWidth;
            const vArea = vH * vW;
            
            const interactive = [];
            const markers = [];
            const walk = (node) => {
                if (node.nodeType === 1) {
                    const tagName = node.tagName.toLowerCase();
                    if (['script', 'style', 'noscript', 'canvas'].includes(tagName)) return;

                    const rect = node.getBoundingClientRect();
                    if (rect.width < 2 || rect.height < 2) {
                        for (let child of node.children) walk(child);
                        return;
                    }

                    const inViewport = (rect.bottom > 0 && rect.right > 0 && rect.top < vH && rect.left < vW);
                const inExtendedViewport = (rect.bottom > 0 && rect.right > 0 && rect.top < (vH + 600) && rect.left < vW);
                
                if (!inExtendedViewport) {
                    for (let child of node.children) walk(child);
                    return;
                }

                    const role = node.getAttribute('role') || '';
                    const style = window.getComputedStyle(node);
                    const isClickable = (
                        ['a', 'button', 'input', 'textarea', 'select'].includes(tagName) ||
                        ['link', 'button', 'checkbox', 'searchbox', 'combobox'].includes(role) ||
                        node.hasAttribute('onclick') || node.hasAttribute('jsaction') ||
                        node.tabIndex >= 0 || style.cursor === 'pointer'
                    );

                    const isHeading = ['h1', 'h2', 'h3'].includes(tagName) || role === 'heading';
                    const isMetaText = (tagName === 'yt-formatted-string' || tagName === 'span') && node.textContent.length >= 12;

                    let label = (node.getAttribute('aria-label') || node.getAttribute('title') || node.getAttribute('placeholder') || node.getAttribute('alt') || "").trim();

                    if (!label) {
                        const areaRatio = (rect.width * rect.height) / vArea;
                        const isSmall = areaRatio <= 0.15 || (rect.height <= 140 && rect.width <= 900);
                        if (isSmall || isHeading || isMetaText) {
                             label = node.textContent.trim().replace(/\\s+/g, ' ').substring(0, 120);
                        }
                    }

                    if (isClickable) {
                        const isSmall = rect.width < 20 && rect.height < 20;
                        if (!label) {
                            label = `[${tagName}${role ? ':' + role : ''}${node.id ? '#' + node.id : ''}]`;
                        }
                        
                        // Prefix small targets to warn the agent they are secondary (menus/icons)
                        if (isSmall) {
                            label = `[small] ${label}`;
                        }

                        interactive.push({
                            tag: tagName, label: label, role: role || (['a', 'link'].includes(tagName) ? 'link' : tagName),
                            bbox: { x: rect.left, y: rect.top, w: rect.width, h: rect.height },
                            area: rect.width * rect.height,
                            center: { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) }
                        });
                    } else if (isHeading || isMetaText) {
                        if (label && label.length >= 8) {
                            markers.push({
                                kind: isHeading ? 'heading' : 'text',
                                text: label,
                                bbox: { x: rect.left, y: rect.top, w: rect.width, h: rect.height },
                                area: rect.width * rect.height
                            });
                        }
                    }

                    for (let child of node.children) walk(child);
                }
            };

            walk(document.body || document.documentElement);

            const dedup = (list) => {
                const res = [];
                const sorted = list.sort((a, b) => a.area - b.area);
                for (const cand of sorted) {
                    if (!res.some(s => {
                        const overlapX = Math.max(0, Math.min(cand.bbox.x + cand.bbox.w, s.bbox.x + s.bbox.w) - Math.max(cand.bbox.x, s.bbox.x));
                        const overlapY = Math.max(0, Math.min(cand.bbox.y + cand.bbox.h, s.bbox.y + s.bbox.h) - Math.max(cand.bbox.y, s.bbox.y));
                        const overlapArea = overlapX * overlapY;
                        return (overlapArea / cand.area > 0.85) || (overlapArea / s.area > 0.85);
                    })) res.push(cand);
                }
                return res;
            };

            const finalNodes = dedup(interactive).sort((a, b) => (Math.round(a.bbox.y / 20) - Math.round(b.bbox.y / 20)) || (a.bbox.x - b.bbox.x));
            const finalMarkers = dedup(markers).slice(0, 15);

            return {
                nodes: finalNodes.map((c, i) => ({ id: `node_${i + 1}`, tag: c.tag, text: c.label, role: c.role, inViewport: true, bbox: c.bbox, hit_point: c.center })),
                markers: finalMarkers.map((m, i) => ({ id: `marker_${i + 1}`, kind: m.kind, text: m.text, bbox: m.bbox })),
                total_count: finalNodes.length,
                viewport_count: finalNodes.length
            };
        })()
        """
        res = await self._call_cdp("Runtime.evaluate", {"expression": js_code, "returnByValue": True})
        return res.get("result", {}).get("value", {"nodes": [], "markers": [], "total_count": 0, "viewport_count": 0})

    async def close(self):
        if self.websocket:
            await self.websocket.close()
        if self.chrome_process:
            self.chrome_process.terminate()
            self.chrome_process.wait()
        if self.session_profile_path and os.path.exists(self.session_profile_path):
            shutil.rmtree(self.session_profile_path, ignore_errors=True)
        logger.info("BrowserRuntime closed and session profile cleaned.")

    async def _wait_for_load(self, timeout: float = 12.0):
        """Wait for document.readyState == 'complete' and check for common SPA loaders."""
        deadline = time.time() + timeout
        
        # Script universal para detectar loaders (spinners, progress bars, etc)
        loader_check_js = """
        (() => {
            const isVisible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
            // Check for common progress bars (YouTube, etc) or spinners
            const loaders = Array.from(document.querySelectorAll('div, span, [role="progressbar"]')).filter(el => {
                const style = window.getComputedStyle(el);
                const isSpinner = style.animationName?.toLowerCase().includes('spin') || 
                                style.animation?.toLowerCase().includes('spin');
                const isProgressBar = el.getAttribute('role') === 'progressbar' || 
                                    el.id?.includes('progress') || 
                                    el.className?.includes('loading-bar');
                return (isSpinner || isProgressBar) && isVisible(el);
            });
            // If the body is unscrollable, it might be a full-screen loader
            const bodyHidden = window.getComputedStyle(document.body).overflow === 'hidden';
            return loaders.length > 0 || bodyHidden;
        })()
        """
        
        while time.time() < deadline:
            try:
                # 1. State check
                res = await self._call_cdp("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
                ready_state = res.get("result", {}).get("value")
                
                # 2. Loader check
                res_loader = await self._call_cdp("Runtime.evaluate", {"expression": loader_check_js, "returnByValue": True})
                is_loading = res_loader.get("result", {}).get("value", False)
                
                if ready_state == "complete" and not is_loading:
                    return
            except: pass
            await asyncio.sleep(0.5)

    async def capture_screenshot_to_file(self) -> str:
        """Captures a screenshot and saves it to a temp file for Vision analysis."""
        res = await self._call_cdp("Page.captureScreenshot", {"format": "png"})
        data = res.get("data")
        if not data:
            raise RuntimeError("Failed to capture screenshot")
        
        path = os.path.join(tempfile.gettempdir(), f"browser_snap_{int(time.time())}.png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path

    async def navigate(self, url: str) -> ToonResponse:
        start_time = time.time()
        try:
            # Get current state before
            before_url = await self._get_current_url()
            before_title = await self._get_current_title()
            
            # Navigate
            await self._call_cdp("Page.navigate", {"url": url})
            
            # Wait for Load
            await self._wait_for_load()
            
            after_url = await self._get_current_url()
            after_title = await self._get_current_title()
            
            return ToonResponse(
                command_id=f"nav_{int(time.time())}",
                component="runtime",
                action="navigate",
                trace_id=self._trace_id,
                step_id="initial",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=await self._generate_evidence(before_url, before_title, "navigate", {"url": url})
            )
        except Exception as e:
            return self._error_response("navigate", str(e), start_time)

    async def _get_current_url(self) -> str:
        try:
            res = await self._call_cdp("Runtime.evaluate", {
                "expression": "window.location.href",
                "returnByValue": True
            })
            return res.get("result", {}).get("value", "") or ""
        except: return ""

    async def _get_current_title(self) -> str:
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
            return res.get("result", {}).get("value", "") or ""
        except: pass
        return ""

    def _error_response(self, action: str, error: str, start_time: float) -> ToonResponse:
        return ToonResponse(
            command_id=f"err_{int(time.time())}",
            component="runtime",
            action=action, # type: ignore
            trace_id=self._trace_id,
            step_id="error",
            status="error",
            execution_time=time.time() - start_time,
            error_details=error
        )

    async def click(self, selector: Optional[str] = None, x: Optional[float] = None, y: Optional[float] = None) -> ToonResponse:
        start_time = time.time()
        try:
            if selector:
                bbox = await self._get_bbox_from_selector(selector)
                x = bbox.x + bbox.width / 2
                y = bbox.y + bbox.height / 2
            
            if x is None or y is None:
                raise ValueError("Must provide selector or coordinates for click")

            # Type refinement
            lx, ly = float(x), float(y)

            # --- INTELLIGENT AUTO-SCROLL ---
            # Get current viewport height
            res_vh = await self._call_cdp("Runtime.evaluate", {"expression": "window.innerHeight", "returnByValue": True})
            vH = float(res_vh.get("result", {}).get("value", 800))

            if ly > vH or ly < 0:
                logger.info(f"Target {ly} is off-screen (vH: {vH}). Performing Auto-Scroll & Recalibration...")
                # Scroll to target (centered better)
                scroll_y = ly - (vH / 2)
                await self._call_cdp("Runtime.evaluate", {"expression": f"window.scrollBy(0, {scroll_y})"})
                await asyncio.sleep(0.8) # Wait for scroll to settle
                # Recalibrate: Target is now at (original - scroll)
                ly = ly - scroll_y
                # Note: lx remains same as we don't handle horizontal auto-scroll yet
            # -------------------------------

            # Mouse Pressed
            await self._call_cdp("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": lx, "y": ly, "button": "left", "clickCount": 1
            })
            # Mouse Released
            await self._call_cdp("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": lx, "y": ly, "button": "left", "clickCount": 1
            })
            
            evidence = await self._generate_evidence("", "", "click", {"x": lx, "y": ly}, target_bbox=BBox(x=lx-5, y=ly-5, width=10, height=10))
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="click",
                trace_id=self._trace_id,
                step_id="step_click",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=evidence
            )
        except Exception as e:
            return self._error_response("click", str(e), start_time)

    async def type_text(self, text: str, selector: Optional[str] = None) -> ToonResponse:
        start_time = time.time()
        try:
            if selector:
                await self.click(selector=selector)
            
            for char in text:
                await self._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "text": char})
                await self._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "text": char})
            
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="type",
                trace_id=self._trace_id,
                step_id="step_type",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=await self._generate_evidence("", "", "type", {"text": text})
            )
        except Exception as e:
            return self._error_response("type", str(e), start_time)

    async def _get_bbox_from_selector(self, selector: str) -> BBox:
        # Get nodes to find the one matching selector
        res = await self._call_cdp("DOM.getFlattenedDocument", {"depth": -1, "pierce": True})
        nodes = res.get("nodes", [])
        
        # We need to find the nodeId for the selector using querySelector on root
        root_node_id = next((n["nodeId"] for n in nodes if n.get("nodeName") == "#document"), None)
        if root_node_id is None:
            raise ValueError("Could not find root node")
            
        node_id_res = await self._call_cdp("DOM.querySelector", {"nodeId": root_node_id, "selector": selector})
        node_id = node_id_res["nodeId"]
        if node_id == 0:
            raise ValueError(f"Element not found: {selector}")
            
        box_model = await self._call_cdp("DOM.getBoxModel", {"nodeId": node_id})
        content = box_model["model"]["content"]
        return BBox(x=content[0], y=content[1], width=content[2]-content[0], height=content[7]-content[1])

    async def _generate_evidence(self, url_before: str, title_before: str, action: str, params: Dict, target_bbox: Optional[BBox] = None) -> EvidencePack:
        # Capture screenshot after
        shot_res = await self._call_cdp("Page.captureScreenshot", {"format": "png"})
        shot_data = shot_res.get("data", "")
        
        # In a real system, save to file. Here we just return a placeholder for brevity in TOON.
        after_ref = f"data:image/png;base64,{shot_data[:50]}..." 
        
        if target_bbox is None:
            target_bbox = BBox(x=0, y=0, width=0, height=0)

        # Mock DOM delta stats for now
        stats = {"added": 0, "removed": 0, "changed": 0}

        return EvidencePack(
            before_screenshot_ref="initial",
            after_screenshot_ref=after_ref,
            url_before=url_before or await self._get_current_url(),
            url_after=await self._get_current_url(),
            title_before=title_before or await self._get_current_title(),
            title_after=await self._get_current_title(),
            target_bbox=target_bbox,
            dom_delta_summary=f"Executed {action}",
            dom_delta_stats=stats,
            console_errors_digest=list(self.console_logs[-5:]),
            network_failures_digest=list(self.network_failures[-5:]),
            cdp_events_digest=[]
        )

    # Step 2: Safe Confirmation Primitives
    async def scroll_into_view(self, selector: str) -> ToonResponse:
        start_time = time.time()
        try:
            res = await self._call_cdp("DOM.getFlattenedDocument", {"depth": 1, "pierce": False})
            root_node_id = res["nodes"][0]["nodeId"]
            node_id_res = await self._call_cdp("DOM.querySelector", {"nodeId": root_node_id, "selector": selector})
            node_id = node_id_res["nodeId"]
            if node_id == 0:
                raise ValueError(f"Element not found: {selector}")
            
            await self._call_cdp("DOM.scrollIntoViewIfNeeded", {"nodeId": node_id})
            
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="scroll",
                trace_id=self._trace_id,
                step_id="step_scroll",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=await self._generate_evidence("", "", "scroll", {"selector": selector})
            )
        except Exception as e:
            return self._error_response("scroll", str(e), start_time)

    async def mouse_move(self, x: float, y: float) -> ToonResponse:
        start_time = time.time()
        try:
            await self._call_cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="scroll", # Reuse scroll or add mouse_move to schema
                trace_id=self._trace_id,
                step_id="step_move",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=await self._generate_evidence("", "", "move", {"x": x, "y": y})
            )
        except Exception as e:
            return self._error_response("scroll", str(e), start_time)

    async def wait(self, seconds: float) -> ToonResponse:
        start_time = time.time()
        await asyncio.sleep(seconds)
        return ToonResponse(
            command_id=f"cmd_{int(time.time())}",
            component="runtime",
            action="wait",
            trace_id=self._trace_id,
            step_id="step_wait",
            status="success",
            execution_time=time.time() - start_time,
            evidence_pack=await self._generate_evidence("", "", "wait", {"seconds": seconds})
        )

    async def capture_screenshot_bytes(self) -> bytes:
        """Captures current viewport as JPG bytes for playback."""
        import base64
        try:
            # We use jpeg for playback to save space
            params = {"format": "jpeg", "quality": 80}
            res = await self._call_cdp("Page.captureScreenshot", params)
            data = res.get("data", "")
            if not data:
                return b""
            return base64.b64decode(data)
        except Exception as e:
            logger.error(f"Failed to capture screenshot bytes: {e}")
            return b""

    async def screenshot(self, full: bool = False) -> ToonResponse:
        start_time = time.time()
        try:
            params = {"format": "png"}
            if full:
                # For full page, we need to get layout metrics
                metrics = await self._call_cdp("Page.getLayoutMetrics")
                width = int(metrics["contentSize"]["width"])
                height = int(metrics["contentSize"]["height"])
                await self._call_cdp("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False
                })
            
            shot_res = await self._call_cdp("Page.captureScreenshot", params)
            evidence = await self._generate_evidence("", "", "screenshot", {"full": full})
            evidence.after_screenshot_ref = f"data:image/png;base64,{shot_res.get('data', '')[:50]}..."
            
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="screenshot",
                trace_id=self._trace_id,
                step_id="step_shot",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=evidence
            )
        except Exception as e:
            return self._error_response("screenshot", str(e), start_time)

    async def dom_snapshot(self) -> ToonResponse:
        start_time = time.time()
        try:
            # CDP DOMSnapshot.captureSnapshot
            res = await self._call_cdp("DOMSnapshot.captureSnapshot", {"computedStyles": []})
            evidence = await self._generate_evidence("", "", "dom_snapshot", {})
            # Store snapshot ref logically
            evidence.dom_snapshot_ref = "captured_snapshot_id"
            
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="dom_snapshot",
                trace_id=self._trace_id,
                step_id="step_dom",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=evidence
            )
        except Exception as e:
            return self._error_response("dom_snapshot", str(e), start_time)
