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
import urllib.request
import urllib.error
import re
import random
import math
from datetime import datetime
from typing import Dict, Any, List, Optional, Union, Literal
from pydantic import BaseModel

from .schemas import ToonResponse, EvidencePack, BBox, BrowserAction

logger = logging.getLogger("aosd.capabilities.browser_control.runtime")
cdp_logger = logging.getLogger("aosd.capabilities.browser_control.cdp")
ext_logger = logging.getLogger("aosd.capabilities.browser_control.extension")
evt_logger = logging.getLogger("aosd.capabilities.browser_control.events")

class BrowserRuntime:
    def __init__(self, 
                 chrome_path: str = "/usr/bin/google-chrome",
                 base_profile_path: str = "data/browser_data/profile",
                 overlay_profile_parent: str = "data/browser_data/profile/sessions",
                 remote_debugging_port: Optional[int] = None,
                 headless: bool = False,
                 muted: bool = False,
                 app_mode: bool = False,
                 launch_url: str = "about:blank",
                 desktop_cache_dir: str = "data/browser_data/desktop_cache",
                 desktop_launch_enabled: bool = True,
                 extension_install_mode: str = "auto",
                 extension_fallback_enabled: bool = True,
                 humanize_input_enabled: bool = True,
                 visual_cursor_enabled: bool = True,
                 tab_user_lock_enabled: bool = True,
                 tab_control_bar_enabled: bool = True,
                 agent_name: str = "Agent"):
        self.chrome_path = chrome_path
        self.base_profile_path = os.path.abspath(base_profile_path)
        self.overlay_profile_parent = os.path.abspath(overlay_profile_parent)
        self.remote_debugging_port = remote_debugging_port
        self.headless = headless
        self.muted = muted
        self.app_mode = app_mode
        self.launch_url = str(launch_url or "about:blank")
        self.desktop_cache_dir = os.path.abspath(desktop_cache_dir)
        self.desktop_launch_enabled = bool(desktop_launch_enabled)
        mode_raw = str(extension_install_mode or "auto").strip().lower()
        self.extension_install_mode = mode_raw if mode_raw in {"auto", "sideload_only", "fallback_only"} else "auto"
        self.extension_fallback_enabled = bool(extension_fallback_enabled)
        self.humanize_input_enabled = bool(humanize_input_enabled)
        self.visual_cursor_enabled = bool(visual_cursor_enabled)
        self.tab_user_lock_enabled = bool(tab_user_lock_enabled)
        self.tab_control_bar_enabled = bool(tab_control_bar_enabled)
        self.agent_name = str(agent_name)
        
        self.session_profile_path: Optional[str] = None
        self.chrome_process: Optional[subprocess.Popen] = None
        self.ws_url: Optional[str] = None
        self.target_id: Optional[str] = None
        self.websocket: Optional[Any] = None
        self._next_id = 1
        self._trace_id = f"trace_{int(time.time())}"
        self._trace_context: Dict[str, str] = {
            "session_id": "",
            "work_id": "",
            "step_id": "",
            "trace_id": self._trace_id,
            "interface": "",
            "channel": "",
        }
        
        # CDP Domains to enable
        self.enabled_domains = ["Page", "DOM", "Runtime", "Network", "Log"]
        self.console_logs: List[str] = []
        self.network_failures: List[Dict[str, Any]] = []
        self._mouse_pos: Dict[str, float] = {"x": 32.0, "y": 32.0}
        self._agent_control_active: bool = False
        self._overlay_refresh_task: Optional[asyncio.Task] = None
        self._overlay_script_registered: bool = False
        self._overlay_fallback_script_registered: bool = False
        self._overlay_fallback_source: str = ""
        self._extension_sideload_attempted: bool = False
        self._extension_sideload_enabled: bool = False
        self._overlay_fallback_used: bool = False
        self._cdp_lock = asyncio.Lock()
        self._skeletal_dom_js = ""

        # Pre-packed Known Sites (Phase 10)
        self.known_sites: Dict[str, Dict[str, str]] = {
            "youtube.com": {"name": "YouTube", "icon": "youtube", "wm_class": "youtube-web"},
            "spotify.com": {"name": "Spotify", "icon": "spotify", "wm_class": "spotify-web"},
            "deezer.com": {"name": "Deezer", "icon": "deezer", "wm_class": "deezer-web"},
            "amazon.com": {"name": "Amazon", "icon": "google-chrome", "wm_class": "amazon-web"},
            "music.amazon.com": {"name": "Amazon Music", "icon": "google-chrome", "wm_class": "amazon-music-web"}
        }

    @staticmethod
    def _compact_for_log(value: Any, max_len: int = 400) -> Any:
        """Return a compact, log-safe representation for CDP payloads/results."""
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                key = str(k)
                if key in {"data", "base64Encoded", "screenshot", "html", "outerHTML"}:
                    if isinstance(v, str):
                        out[key] = f"<omitted:{len(v)} chars>"
                    else:
                        out[key] = "<omitted>"
                    continue
                out[key] = BrowserRuntime._compact_for_log(v, max_len=max_len)
            return out
        if isinstance(value, list):
            if len(value) > 20:
                return [BrowserRuntime._compact_for_log(item, max_len=max_len) for item in value[:20]] + [f"... +{len(value) - 20} items"]
            return [BrowserRuntime._compact_for_log(item, max_len=max_len) for item in value]
        text = str(value)
        if len(text) > max_len:
            return text[:max_len] + "...<truncated>"
        return value

    @staticmethod
    def _cdp_log_level(method: str) -> int:
        noisy_prefixes = ("Input.dispatchMouseEvent", "Input.dispatchKeyEvent")
        if any(method.startswith(prefix) for prefix in noisy_prefixes):
            return logging.DEBUG
        return logging.INFO

    def _trace_ctx(self, **extra: str) -> Dict[str, str]:
        ctx = dict(self._trace_context)
        ctx["trace_id"] = str(self._trace_id or ctx.get("trace_id") or "")
        for key, value in extra.items():
            if value is None:
                continue
            ctx[str(key)] = str(value)
        return ctx

    def set_trace_context(
        self,
        *,
        session_id: str = "",
        work_id: str = "",
        trace_id: str = "",
        interface: str = "",
        channel: str = "",
    ) -> None:
        if session_id:
            self._trace_context["session_id"] = str(session_id)
        if work_id:
            self._trace_context["work_id"] = str(work_id)
        if interface:
            self._trace_context["interface"] = str(interface)
        if channel:
            self._trace_context["channel"] = str(channel)
        if trace_id:
            self._trace_id = str(trace_id)
            self._trace_context["trace_id"] = self._trace_id
        else:
            self._trace_context["trace_id"] = str(self._trace_id)

    def set_step_context(self, *, step_id: str = "", trace_id: str = "") -> None:
        self._trace_context["step_id"] = str(step_id or "")
        if trace_id:
            self._trace_id = str(trace_id)
        self._trace_context["trace_id"] = str(self._trace_id)

    @staticmethod
    def _is_subpath(path: str, parent: str) -> bool:
        try:
            path_real = os.path.realpath(path)
            parent_real = os.path.realpath(parent)
            return os.path.commonpath([path_real, parent_real]) == parent_real
        except Exception:
            return False

    def _build_profile_copy_ignore(self):
        """
        Prevent recursive copy when overlay path lives inside base profile path.
        Example:
        - base: data/browser_data/profile
        - overlay parent: data/browser_data/profile/sessions
        """
        base_real = os.path.realpath(self.base_profile_path)
        overlay_parent_real = os.path.realpath(self.overlay_profile_parent)

        if not self._is_subpath(overlay_parent_real, base_real):
            return None

        rel = os.path.relpath(overlay_parent_real, base_real)
        first_component = rel.split(os.sep, 1)[0] if rel else ""
        if not first_component or first_component == ".":
            logger.warning(
                "Overlay profile parent is the same as base profile path. "
                "Skipping base profile copy to avoid recursive copy."
            )
            return "__SKIP_COPY__"

        logger.warning(
            "Overlay parent is nested inside base profile; ignoring top-level '%s' during copy.",
            first_component,
        )

        def _ignore(path: str, names: List[str]) -> List[str]:
            try:
                ignored = []
                if os.path.realpath(path) == base_real and first_component in names:
                    ignored.append(first_component)
                
                # Always ignore singleton locks to prevent new processes from
                # joining existing ones and ignoring our startup flags (like --load-extension)
                for lock_file in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
                    if lock_file in names:
                        ignored.append(lock_file)
                        
                return ignored
            except Exception:
                return []
            return []

        return _ignore

    @staticmethod
    def _sanitize_slug(value: str, fallback: str = "web-app") -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
        return slug or fallback

    def _site_identity(self, url: str) -> Dict[str, str]:
        parsed = urllib.parse.urlparse(str(url or ""))
        host = str(parsed.netloc or "").lower()
        host = host.split(":")[0]
        host_nw = host[4:] if host.startswith("www.") else host
        
        # 1. Check Pre-pack (Phase 10)
        for domain, meta in self.known_sites.items():
            if domain in host_nw:
                return {
                    "slug": self._sanitize_slug(host_nw),
                    "wm_class": meta["wm_class"],
                    "name": meta["name"],
                    "icon": meta["icon"]
                }

        # 2. Heuristic fallback
        root = host_nw.split(".")[0] if host_nw else "web"
        slug = self._sanitize_slug(host_nw or root, fallback="web-app")
        wm_class = self._sanitize_slug(f"{root}-web", fallback="web-app")
        pretty = root.capitalize() if root else "Web"
        return {"slug": slug, "wm_class": wm_class, "name": pretty, "icon": "google-chrome"}

    @staticmethod
    def _guess_ext_from_content_type(content_type: str, fallback: str = ".png") -> str:
        ct = str(content_type or "").lower()
        if "svg" in ct:
            return ".svg"
        if "x-icon" in ct or "icon" in ct:
            return ".ico"
        if "jpeg" in ct or "jpg" in ct:
            return ".jpg"
        if "png" in ct:
            return ".png"
        return fallback

    @staticmethod
    def _download_bytes(url: str, timeout_s: float = 3.0, max_bytes: int = 1_500_000) -> Optional[Dict[str, Any]]:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121 Safari/537.36",
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = resp.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    return None
                content_type = str(resp.headers.get("Content-Type") or "").strip()
                return {"bytes": payload, "content_type": content_type}
        except Exception:
            return None

    @staticmethod
    def _extract_manifest_href(html: str) -> str:
        # Prefer explicit rel=manifest links.
        patterns = [
            r'<link[^>]+rel=["\']manifest["\'][^>]+href=["\']([^"\']+)["\']',
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']manifest["\']',
        ]
        for pat in patterns:
            m = re.search(pat, html, flags=re.IGNORECASE)
            if m and m.group(1):
                return m.group(1).strip()
        return ""

    @staticmethod
    def _pick_manifest_icon(manifest_obj: Dict[str, Any]) -> str:
        icons = manifest_obj.get("icons")
        if not isinstance(icons, list):
            return ""
        best_src = ""
        best_score = -1
        for item in icons:
            if not isinstance(item, dict):
                continue
            src = str(item.get("src") or "").strip()
            if not src:
                continue
            sizes = str(item.get("sizes") or "").lower()
            score = 1
            # Pick biggest declared size (e.g. "512x512")
            for token in sizes.split():
                parts = token.split("x")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    score = max(score, int(parts[0]) * int(parts[1]))
            purpose = str(item.get("purpose") or "").lower()
            if "maskable" in purpose:
                score += 1000
            if score > best_score:
                best_score = score
                best_src = src
        return best_src

    def _resolve_desktop_icon(self, launch_url: str, desktop_id: str, fallback_icon: str) -> str:
        """
        Try to fetch PWA-style icon (manifest icons), then favicon fallback.
        Returns icon path for .desktop or themed icon fallback.
        """
        try:
            parsed = urllib.parse.urlparse(str(launch_url or ""))
            if not parsed.scheme or not parsed.netloc:
                return fallback_icon
            origin = f"{parsed.scheme}://{parsed.netloc}"
            icons_dir = os.path.join(self.desktop_cache_dir, "icons")
            os.makedirs(icons_dir, exist_ok=True)

            # 1) Try manifest icon from HTML
            html_blob = self._download_bytes(origin, timeout_s=3.0, max_bytes=900_000)
            manifest_icon_url = ""
            if html_blob and isinstance(html_blob.get("bytes"), (bytes, bytearray)):
                try:
                    html = bytes(html_blob["bytes"]).decode("utf-8", errors="ignore")
                except Exception:
                    html = ""
                manifest_href = self._extract_manifest_href(html)
                if manifest_href:
                    manifest_url = urllib.parse.urljoin(origin + "/", manifest_href)
                    manifest_blob = self._download_bytes(manifest_url, timeout_s=3.0, max_bytes=700_000)
                    if manifest_blob and isinstance(manifest_blob.get("bytes"), (bytes, bytearray)):
                        try:
                            manifest_obj = json.loads(bytes(manifest_blob["bytes"]).decode("utf-8", errors="ignore"))
                            src = self._pick_manifest_icon(manifest_obj if isinstance(manifest_obj, dict) else {})
                            if src:
                                manifest_icon_url = urllib.parse.urljoin(manifest_url, src)
                        except Exception:
                            manifest_icon_url = ""

            # 2) Fallback icon candidates
            candidates: List[str] = []
            if manifest_icon_url:
                candidates.append(manifest_icon_url)
            candidates.extend(
                [
                    urllib.parse.urljoin(origin + "/", "/favicon.ico"),
                    urllib.parse.urljoin(origin + "/", "/favicon-32x32.png"),
                    urllib.parse.urljoin(origin + "/", "/apple-touch-icon.png"),
                ]
            )

            for candidate in candidates:
                blob = self._download_bytes(candidate, timeout_s=3.0, max_bytes=2_000_000)
                if not blob:
                    continue
                data = blob.get("bytes")
                if not isinstance(data, (bytes, bytearray)) or not data:
                    continue
                ext = self._guess_ext_from_content_type(blob.get("content_type") or "")
                if ext == ".png" and candidate.lower().endswith(".svg"):
                    ext = ".svg"
                if ext == ".png" and candidate.lower().endswith(".ico"):
                    ext = ".ico"
                icon_path = os.path.join(icons_dir, f"{desktop_id}{ext}")
                try:
                    with open(icon_path, "wb") as f:
                        f.write(bytes(data))
                    return icon_path
                except Exception:
                    continue
        except Exception:
            return fallback_icon
        return fallback_icon

    @staticmethod
    def _write_if_changed(path: str, content: str, mode: Optional[int] = None) -> None:
        current = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    current = f.read()
            except Exception:
                current = ""
        if current != content:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        if mode is not None:
            try:
                os.chmod(path, mode)
            except Exception:
                pass

    @staticmethod
    def _safe_load_json(path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _safe_dump_json(path: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)

    def _enforce_clean_startup_preferences(self, user_data_dir: str) -> None:
        """
        Force Chrome startup behavior to open a fresh window/tab instead of restoring
        the previous session from the persistent profile.
        """
        try:
            prefs_path = os.path.join(user_data_dir, "Default", "Preferences")
            prefs = self._safe_load_json(prefs_path)
            session = prefs.get("session")
            if not isinstance(session, dict):
                session = {}
                prefs["session"] = session
            session["restore_on_startup"] = 5  # open New Tab page
            session["startup_urls"] = []
            session["urls_to_restore_on_startup"] = []
            session["restore_apps_and_pages_on_startup"] = 5

            profile = prefs.get("profile")
            if not isinstance(profile, dict):
                profile = {}
                prefs["profile"] = profile
            profile["exit_type"] = "Normal"
            profile["exited_cleanly"] = True

            self._safe_dump_json(prefs_path, prefs)

            # Also mark local state as clean to reduce crash-restore prompts.
            local_state_path = os.path.join(user_data_dir, "Local State")
            local_state = self._safe_load_json(local_state_path)
            ls_profile = local_state.get("profile")
            if not isinstance(ls_profile, dict):
                ls_profile = {}
                local_state["profile"] = ls_profile
            ls_profile["last_used"] = str(ls_profile.get("last_used") or "Default")
            self._safe_dump_json(local_state_path, local_state)
        except Exception as e:
            logger.warning("Failed to enforce clean startup preferences: %s", e)

    def _ensure_site_desktop_bundle(self, url: str) -> Dict[str, str]:
        ident = self._site_identity(url)
        slug = ident["slug"]
        desktop_id = f"agent-{slug}"
        wm_class = ident["wm_class"]
        icon_value = self._resolve_desktop_icon(url, desktop_id, ident["icon"])

        desktop_dir = os.path.join(self.desktop_cache_dir, "desktop")
        desktop_path = os.path.join(desktop_dir, f"{desktop_id}.desktop")
        user_desktop_path = os.path.expanduser(f"~/.local/share/applications/{desktop_id}.desktop")

        desktop = f"""[Desktop Entry]
Name={ident["name"]}
Exec={self.chrome_path} --app={url} --class={wm_class}
Terminal=false
Type=Application
Icon={icon_value}
StartupWMClass={wm_class}
Categories=Network;AudioVideo;
"""
        self._write_if_changed(desktop_path, desktop)
        self._write_if_changed(user_desktop_path, desktop)
        return {
            "desktop_id": desktop_id,
            "desktop_path": desktop_path,
            "wm_class": wm_class,
        }

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
        
        # Use base profile directly as requested
        self.session_profile_path = self.base_profile_path
        self._enforce_clean_startup_preferences(self.session_profile_path)

        app_bundle: Dict[str, str] = {}
        wm_class = ""
        if self.app_mode and self.launch_url and self.launch_url != "about:blank":
            try:
                # PHASE 10: Immediate identity lookup (non-blocking)
                ident = self._site_identity(self.launch_url)
                wm_class = ident["wm_class"]
                # Background full bundle setup (Icon fetch, etc.)
                asyncio.create_task(asyncio.to_thread(self._ensure_site_desktop_bundle, self.launch_url))
            except Exception as e:
                logger.warning(f"Desktop identity setup failed: {e}")

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
            # "--disable-extensions", # Enabled for the overlay extension
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
            if wm_class:
                args.append(f"--class={wm_class}")
            args.append(f"--app={self.launch_url}")
        else:
            args.append("--new-window")
            args.append(self.launch_url)

        # Extension loading
        ext_path = os.path.join(os.path.dirname(__file__), "extension")
        allow_sideload = self.extension_install_mode in {"auto", "sideload_only"}
        if os.path.exists(ext_path) and allow_sideload:
            args.append(f"--load-extension={ext_path}")
            args.append(f"--disable-extensions-except={ext_path}")
            args.append("--enable-automation")
            self._extension_sideload_attempted = True
            self._extension_sideload_enabled = True
            logger.info(f"Loading browser control extension from {ext_path}")
        elif os.path.exists(ext_path):
            logger.info("Extension sideload disabled by config (extension_install_mode=%s).", self.extension_install_mode)
        else:
            logger.warning(f"Browser control extension not found at {ext_path}")

        try:
            self.chrome_process = subprocess.Popen(
                args,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
            class_str = app_bundle.get("wm_class", "") if self.app_mode else ""
            logger.info(f"Launched Chrome | pid={self.chrome_process.pid} app_mode={self.app_mode} class={class_str}")
        except Exception as e:
            raise RuntimeError(f"Failed to launch Chrome: {e}")
        
        # Wait for WS endpoint to be available
        start_time = time.time()
        while time.time() - start_time < 10:
            if self.chrome_process and self.chrome_process.poll() is not None:
                raise RuntimeError(
                    "Chrome process exited immediately. This usually means another Chrome "
                    "instance is already running with the same profile directory. "
                    "To use the base profile directly with the Agent extension, you must close "
                    "all existing Chrome windows first."
                )
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
        await self._register_overlay_script_on_new_document()
        if self.extension_fallback_enabled:
            await self._register_overlay_fallback_script_on_new_document()
        await self._wait_for_load(timeout=8.0)
        if self.extension_fallback_enabled:
            await self._inject_overlay_fallback_now()
        await self._ensure_control_overlay()
            
        logger.info("CDP Handshake successful and domains enabled.")

    def get_connection_metadata(self) -> Dict[str, Any]:
        return {
            "debug_port": self.remote_debugging_port,
            "ws_url": self.ws_url,
            "target_id": self.target_id,
            "app_mode": self.app_mode,
            "launch_url": self.launch_url,
            "humanize_input_enabled": self.humanize_input_enabled,
            "visual_cursor_enabled": self.visual_cursor_enabled,
            "tab_user_lock_enabled": self.tab_user_lock_enabled,
            "tab_control_bar_enabled": self.tab_control_bar_enabled,
            "extension_install_mode": self.extension_install_mode,
            "extension_fallback_enabled": self.extension_fallback_enabled,
            "extension_sideload_attempted": self._extension_sideload_attempted,
            "extension_sideload_enabled": self._extension_sideload_enabled,
            "overlay_fallback_used": self._overlay_fallback_used,
        }

    async def _push_overlay_sync(self, payload: Dict[str, Any], verify: bool = False) -> None:
        """
        Bridge runtime -> extension through document.dataset so it works with
        MV3 isolated world content scripts.
        """
        data = dict(payload or {})
        data["_ts"] = int(time.time() * 1000)
        data_json = json.dumps(data, separators=(",", ":"))
        expr = f"""
        (() => {{
          const ds = document.documentElement.dataset;
          ds.agentControlSync = {json.dumps(data_json)};
          return true;
        }})()
        """
        try:
            ext_logger.debug("overlay.sync.push %s", json.dumps(self._trace_ctx(verify=str(bool(verify))), ensure_ascii=False))
            await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            if verify:
                await self._verify_control_overlay_state()
        except Exception:
            ext_logger.exception("overlay.sync.push.failed %s", json.dumps(self._trace_ctx(), ensure_ascii=False))
            pass

    def _load_overlay_fallback_source(self) -> str:
        if self._overlay_fallback_source:
            return self._overlay_fallback_source
        ext_content = os.path.join(os.path.dirname(__file__), "extension", "content.js")
        try:
            with open(ext_content, "r", encoding="utf-8") as f:
                src = f.read()
            self._overlay_fallback_source = str(src or "")
            return self._overlay_fallback_source
        except Exception:
            return ""

    async def _register_overlay_fallback_script_on_new_document(self) -> None:
        if self._overlay_fallback_script_registered:
            return
        src = self._load_overlay_fallback_source()
        if not src.strip():
            return
        try:
            await self._call_cdp(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": src},
            )
            self._overlay_fallback_script_registered = True
            ext_logger.info("overlay.fallback.registered %s", json.dumps(self._trace_ctx(), ensure_ascii=False))
        except Exception as e:
            logger.debug(f"Overlay fallback registration skipped: {e}")
            ext_logger.debug("overlay.fallback.register.skipped %s", json.dumps(self._trace_ctx(error=str(e)), ensure_ascii=False))

    async def _inject_overlay_fallback_now(self) -> None:
        if not self.extension_fallback_enabled:
            return
        src = self._load_overlay_fallback_source()
        if not src.strip():
            return
        try:
            await self._call_cdp("Runtime.evaluate", {"expression": src, "returnByValue": True})
            self._overlay_fallback_used = True
            ext_logger.info("overlay.fallback.injected %s", json.dumps(self._trace_ctx(), ensure_ascii=False))
        except Exception:
            ext_logger.exception("overlay.fallback.inject.failed %s", json.dumps(self._trace_ctx(), ensure_ascii=False))
            pass

    async def _ensure_control_overlay(self) -> None:
        if not (self.visual_cursor_enabled or self.tab_user_lock_enabled or self.tab_control_bar_enabled):
            return
        payload = {
            "lock_enabled": bool(self.tab_user_lock_enabled),
            "cursor_enabled": bool(self.visual_cursor_enabled),
            "bar_enabled": bool(self.tab_control_bar_enabled),
            "active": bool(self._agent_control_active),
            "cursor_x": float(self._mouse_pos.get("x", 32.0)),
            "cursor_y": float(self._mouse_pos.get("y", 32.0)),
            "agent_name": self.agent_name
        }
        await self._push_overlay_sync(payload, verify=True)
        state = await self._read_control_overlay_state()
        ext_logger.debug(
            "overlay.ensure.state %s",
            json.dumps(self._trace_ctx(state=json.dumps(self._compact_for_log(state), ensure_ascii=False)), ensure_ascii=False),
        )
        if (not bool(state.get("control_present"))) and self.extension_fallback_enabled:
            await self._inject_overlay_fallback_now()
            await self._push_overlay_sync(payload, verify=True)

    async def _register_overlay_script_on_new_document(self) -> None:
        """
        Register a tiny bootstrap script so new documents already have control state
        placeholders; full style/handlers are reinforced by _ensure_control_overlay.
        """
        if self._overlay_script_registered:
            return
        initial_sync = {
            "active": bool(self._agent_control_active),
            "paused": False,
            "agent_input": False,
            "resume_requested": False,
            "resume_context": "",
            "lock_enabled": bool(self.tab_user_lock_enabled),
            "cursor_enabled": bool(self.visual_cursor_enabled),
            "bar_enabled": bool(self.tab_control_bar_enabled),
            "cursor_x": float(self._mouse_pos.get("x", 32.0)),
            "cursor_y": float(self._mouse_pos.get("y", 32.0)),
            "agent_name": self.agent_name,
            "_ts": int(time.time() * 1000),
        }
        expr = f"""
        (() => {{
          const ds = document.documentElement.dataset;
          ds.agentActive = {json.dumps(str(bool(self._agent_control_active)).lower())};
          ds.agentPaused = "false";
          ds.agentInput = "false";
          ds.agentResumeRequested = "false";
          ds.agentResumeContext = "";
          if (!ds.agentGuardInstalled) ds.agentGuardInstalled = "false";
          ds.agentControlSync = {json.dumps(json.dumps(initial_sync, separators=(",", ":")))};
        }})()
        """
        try:
            await self._call_cdp(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": expr},
            )
            self._overlay_script_registered = True
        except Exception as e:
            logger.debug(f"Overlay bootstrap registration skipped: {e}")

    async def _is_document_complete(self) -> bool:
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            return str(res.get("result", {}).get("value", "")) == "complete"
        except Exception:
            return False

    async def _read_control_overlay_state(self) -> Dict[str, Any]:
        expr = r"""
        (() => {
          const ds = document.documentElement.dataset;
          const host = document.getElementById("agent-host");
          
          return {
            ready_state: String(document.readyState || ""),
            control_present: !!host,
            active: ds.agentActive === "true",
            paused: ds.agentPaused === "true",
            agent_input: ds.agentInput === "true",
            guard_installed: ds.agentGuardInstalled === "true",
            lock_present: !!host,
            cursor_present: !!host,
            bar_present: !!host,
            lock_visible: !!host && ds.agentActive === "true" && ds.agentPaused !== "true",
            cursor_visible: !!host && ds.agentActive === "true" && ds.agentPaused !== "true",
            bar_visible: !!host && ds.agentActive === "true",
            resume_requested: ds.agentResumeRequested === "true",
            resume_context: ds.agentResumeContext || ""
          };
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    async def _verify_control_overlay_state(self, retries: int = 3, delay_s: float = 0.12) -> Dict[str, Any]:
        """
        Validate that overlay elements exist and, when active, are visible as expected.
        """
        last: Dict[str, Any] = {}
        for _ in range(max(1, int(retries))):
            state = await self._read_control_overlay_state()
            last = state
            if not state:
                await asyncio.sleep(delay_s)
                continue
            if not state.get("control_present"):
                await asyncio.sleep(delay_s)
                continue
            if not (state.get("cursor_present") and state.get("bar_present")):
                await asyncio.sleep(delay_s)
                continue
            if self._agent_control_active:
                cursor_ok = (not self.visual_cursor_enabled) or bool(state.get("cursor_visible"))
                # Bar can be intentionally hidden and only shown on user interaction hints.
                bar_ok = (not self.tab_control_bar_enabled) or bool(state.get("bar_present"))
                guard_ok = (not self.tab_user_lock_enabled) or bool(state.get("guard_installed"))
                if cursor_ok and bar_ok and guard_ok:
                    return state
                await asyncio.sleep(delay_s)
                continue
            return state

        if last:
            logger.warning(f"Overlay verification failed: {last}")
            ext_logger.warning(
                "overlay.verify.failed %s",
                json.dumps(self._trace_ctx(state=json.dumps(self._compact_for_log(last), ensure_ascii=False)), ensure_ascii=False),
            )
        else:
            logger.warning("Overlay verification failed: no state returned.")
            ext_logger.warning("overlay.verify.failed.no_state %s", json.dumps(self._trace_ctx(), ensure_ascii=False))
        return last

    def _schedule_overlay_refresh(self) -> None:
        if not self._agent_control_active:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._overlay_refresh_task and not self._overlay_refresh_task.done():
            return

        async def _refresh() -> None:
            try:
                await self._wait_for_load(timeout=8.0)
                await self._ensure_control_overlay()
                if self._agent_control_active:
                    await self.set_agent_control_active(True)
                await self._verify_control_overlay_state()
            except Exception:
                pass

        self._overlay_refresh_task = loop.create_task(_refresh())

    async def set_agent_control_active(self, active: bool) -> None:
        self._agent_control_active = bool(active)
        if self._agent_control_active:
            try:
                await self._wait_for_load(timeout=8.0)
            except Exception:
                pass
        await self._ensure_control_overlay()

    async def get_tab_control_state(self) -> Dict[str, Any]:
        if not self.tab_control_bar_enabled:
            return {"paused": False, "resume_requested": False, "resume_context": "", "active": self._agent_control_active}
        await self._ensure_control_overlay()
        expr = r"""
        (() => {
          const ds = document.documentElement.dataset;
          const asBool = (v) => String(v || "").toLowerCase() === "true";
          const out = {
            paused: asBool(ds.agentPaused),
            resume_requested: asBool(ds.agentResumeRequested),
            resume_context: String(ds.agentResumeContext || ""),
            active: asBool(ds.agentActive)
          };
          if (out.resume_requested) {
            ds.agentResumeRequested = "false";
            ds.agentResumeContext = "";
            ds.agentControlSync = JSON.stringify({
              resume_requested: false,
              resume_context: "",
              _ts: Date.now()
            });
          }
          return out;
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            if isinstance(value, dict):
                return value
        except Exception:
            pass
        return {"paused": False, "resume_requested": False, "resume_context": "", "active": self._agent_control_active}

    async def _update_cursor_overlay(self, x: float, y: float) -> None:
        self._mouse_pos = {"x": float(x), "y": float(y)}
        if not self.visual_cursor_enabled:
            return
        await self._push_overlay_sync({"cursor_x": float(x), "cursor_y": float(y)})

    async def _human_move_to(self, target_x: float, target_y: float) -> None:
        sx = float(self._mouse_pos.get("x", 32.0))
        sy = float(self._mouse_pos.get("y", 32.0))
        tx = float(target_x)
        ty = float(target_y)
        distance = math.hypot(tx - sx, ty - sy)
        steps = int(max(8, min(40, distance / 15.0)))
        for i in range(1, steps + 1):
            t = i / steps
            eased = (3 * (t ** 2)) - (2 * (t ** 3))
            jitter = min(2.0, max(0.0, distance / 250.0))
            px = sx + (tx - sx) * eased + random.uniform(-jitter, jitter)
            py = sy + (ty - sy) * eased + random.uniform(-jitter, jitter)
            await self._call_cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py})
            await self._update_cursor_overlay(px, py)
            await asyncio.sleep(random.uniform(0.008, 0.022))
        await self._call_cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": tx, "y": ty})
        await self._update_cursor_overlay(tx, ty)

    async def _human_click(self, x: float, y: float) -> None:
        await self._human_move_to(x, y)
        await asyncio.sleep(random.uniform(0.02, 0.08))
        await self._call_cdp("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1
        })
        await asyncio.sleep(random.uniform(0.035, 0.13))
        await self._call_cdp("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1
        })
        await self._update_cursor_overlay(x, y)

    async def _set_agent_input_window(self, enabled: bool) -> None:
        await self._push_overlay_sync({"agent_input": bool(enabled)})

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
            await self._ensure_control_overlay()
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
        started = time.perf_counter()
        level = self._cdp_log_level(method)
        cdp_logger.log(
            level,
            "cdp.request %s",
            json.dumps(
                {
                    **self._trace_ctx(method=method, msg_id=str(msg_id)),
                    "params": self._compact_for_log(payload["params"]),
                },
                ensure_ascii=False,
            ),
        )

        async with self._cdp_lock:
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
                            duration_ms = round((time.perf_counter() - started) * 1000, 2)
                            cdp_logger.error(
                                "cdp.response.error %s",
                                json.dumps(
                                    {
                                        **self._trace_ctx(method=method, msg_id=str(msg_id), duration_ms=str(duration_ms)),
                                        "error": self._compact_for_log(data.get("error", {})),
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                            raise RuntimeError(f"CDP Error ({method}): {data['error'].get('message')}")
                        result = data.get("result")
                        duration_ms = round((time.perf_counter() - started) * 1000, 2)
                        cdp_logger.log(
                            level,
                            "cdp.response %s",
                            json.dumps(
                                {
                                    **self._trace_ctx(method=method, msg_id=str(msg_id), duration_ms=str(duration_ms)),
                                    "result": self._compact_for_log(result),
                                },
                                ensure_ascii=False,
                            ),
                        )
                        return result
                except Exception as e:
                    import websockets
                    if isinstance(e, websockets.ConnectionClosed):
                        cdp_logger.error(
                            "cdp.connection.closed %s",
                            json.dumps(self._trace_ctx(method=method, msg_id=str(msg_id)), ensure_ascii=False),
                        )
                        raise RuntimeError("CDP connection closed")
                    cdp_logger.error(
                        "cdp.request.failed %s",
                        json.dumps(self._trace_ctx(method=method, msg_id=str(msg_id), error=str(e)), ensure_ascii=False),
                    )
                    raise

    def _handle_cdp_event(self, data: Dict[str, Any]):
        method = data.get("method")
        params = data.get("params", {})
        important_events = {"Page.loadEventFired", "Runtime.exceptionThrown", "Network.loadingFailed", "Log.entryAdded"}
        if method in important_events:
            evt_logger.info(
                "cdp.event %s",
                json.dumps(
                    {
                        **self._trace_ctx(method=str(method or "")),
                        "params": self._compact_for_log(params),
                    },
                    ensure_ascii=False,
                ),
            )
        
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
        elif method == "Page.loadEventFired":
            self._schedule_overlay_refresh()

    async def get_skeletal_dom(self) -> Dict[str, Any]:
        """
        UI Snapshot Generator: Transforms raw DOM into TWO streams via skeletal_dom.js
        """
        if not self._skeletal_dom_js:
            js_path = os.path.join(os.path.dirname(__file__), "skeletal_dom.js")
            try:
                with open(js_path, "r", encoding="utf-8") as f:
                    self._skeletal_dom_js = f.read()
            except Exception as e:
                logger.error(f"Failed to load skeletal_dom.js: {e}")
                return {"nodes": [], "markers": [], "total_count": 0, "viewport_count": 0}

        res = await self._call_cdp("Runtime.evaluate", {"expression": self._skeletal_dom_js, "returnByValue": True})
        return res.get("result", {}).get("value", {"nodes": [], "markers": [], "total_count": 0, "viewport_count": 0})

    async def close(self):
        try:
            await self.set_agent_control_active(False)
        except Exception:
            pass
        if self.websocket:
            await self.websocket.close()
        if self.chrome_process:
            self.chrome_process.terminate()
            self.chrome_process.wait()
        # Removed session profile cleanup as we use the persistent base profile directly
        logger.info("BrowserRuntime closed.")

    def force_close(self):
        """
        Best-effort synchronous close for cross-loop teardown.
        Avoids awaiting websocket on a different event loop.
        """
        try:
            if self.chrome_process:
                self.chrome_process.terminate()
                try:
                    self.chrome_process.wait(timeout=3)
                except Exception:
                    try:
                        self.chrome_process.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        # Removed session profile cleanup as we use the persistent base profile directly
        self.websocket = None
        self.chrome_process = None
        logger.info("BrowserRuntime force-closed (sync teardown).")

    async def _wait_for_load(self, timeout: float = 8.0):
        """
        Lightweight native page readiness guard.
        Uses readyState + minimal DOM availability and avoids heuristic loader detection.
        """
        deadline = time.time() + max(0.5, float(timeout))
        check_js = r"""
        (() => ({
            readyState: String(document.readyState || ""),
            hasBody: !!document.body,
            nodeCount: Number(document.getElementsByTagName("*").length || 0)
        }))()
        """

        while time.time() < deadline:
            try:
                res = await self._call_cdp("Runtime.evaluate", {"expression": check_js, "returnByValue": True})
                value = res.get("result", {}).get("value", {}) if isinstance(res, dict) else {}
                if not isinstance(value, dict):
                    value = {}
                ready_state = str(value.get("readyState", ""))
                has_body = bool(value.get("hasBody"))
                node_count = int(value.get("nodeCount") or 0)

                if ready_state == "complete" and has_body:
                    return
                if ready_state == "interactive" and has_body and node_count >= 10:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.35)

        logger.warning("wait_for_load timeout reached; proceeding with current page state.")

    async def capture_screenshot_to_file(self, image_format: str = "png", quality: Optional[int] = None) -> str:
        """Captures a screenshot and saves it to a temp file for Vision analysis."""
        fmt = str(image_format or "png").strip().lower()
        if fmt not in {"png", "jpeg"}:
            fmt = "png"
        params: Dict[str, Any] = {"format": fmt}
        if fmt == "jpeg":
            q = int(quality if quality is not None else 70)
            params["quality"] = max(25, min(95, q))
        res = await self._call_cdp("Page.captureScreenshot", params)
        data = res.get("data")
        if not data:
            raise RuntimeError("Failed to capture screenshot")

        ext = "jpg" if fmt == "jpeg" else "png"
        path = os.path.join(tempfile.gettempdir(), f"browser_snap_{int(time.time())}.{ext}")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path

    async def get_page_signature(self) -> Dict[str, Any]:
        """
        Cheap state signature used for perception cache decisions.
        Avoids expensive DOM+Vision recomputation when stable.
        """
        expr = r"""
        (() => {
            const focus = document.activeElement;
            const tag = String(focus?.tagName || "").toLowerCase();
            const role = String(focus?.getAttribute?.("role") || "");
            const id = String(focus?.id || "");
            const childCount = Number(document.body?.childElementCount || 0);
            return {
                url: String(window.location.href || ""),
                title: String(document.title || ""),
                ready: String(document.readyState || ""),
                scroll_x: Number(window.scrollX || 0),
                scroll_y: Number(window.scrollY || 0),
                vw: Number(window.innerWidth || 0),
                vh: Number(window.innerHeight || 0),
                time_origin: Number((performance && performance.timeOrigin) || 0),
                focus_tag: tag,
                focus_role: role,
                focus_id: id,
                body_children: childCount
            };
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            if isinstance(value, dict):
                return value
        except Exception:
            pass
        return {}

    async def navigate(self, url: str) -> ToonResponse:
        start_time = time.time()
        try:
            await self._ensure_control_overlay()
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
                evidence_pack=await self._generate_evidence(before_url, before_title, "navigate", {"url": url}),
                result_data={
                    "kind": "navigate_action_receipt_v1",
                    "requested_url": str(url or ""),
                    "url_before": str(before_url or ""),
                    "url_after": str(after_url or ""),
                    "title_before": str(before_title or ""),
                    "title_after": str(after_title or ""),
                },
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

    async def get_page_info(self) -> Dict[str, Any]:
        """
        Runtime-agnostic page info contract for planner:
        {url, title, viewport:{w,h}}
        """
        try:
            expr = (
                "JSON.stringify({"
                "url:String(window.location.href||''),"
                "title:String(document.title||''),"
                "w:Number(window.innerWidth||0),"
                "h:Number(window.innerHeight||0)"
                "})"
            )
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            raw = res.get("result", {}).get("value", "{}")
            if isinstance(raw, str):
                data = json.loads(raw or "{}")
            elif isinstance(raw, dict):
                data = raw
            else:
                data = {}
            return {
                "url": str(data.get("url", "") or ""),
                "title": str(data.get("title", "") or ""),
                "viewport": {
                    "w": int(data.get("w", 0) or 0),
                    "h": int(data.get("h", 0) or 0),
                },
            }
        except Exception:
            return {
                "url": await self._get_current_url(),
                "title": await self._get_current_title(),
                "viewport": {"w": 0, "h": 0},
            }

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
            await self._ensure_control_overlay()
            await self._set_agent_input_window(True)
            if selector:
                bbox = await self._get_bbox_from_selector(selector)
                x = bbox.x + bbox.width / 2
                y = bbox.y + bbox.height / 2
            
            if x is None or y is None:
                raise ValueError("Must provide selector or coordinates for click")

            # Type refinement
            lx, ly = float(x), float(y)
            before_focus = await self._get_runtime_focus_context()
            before_mouse_probe = await self._get_mouse_probe_snapshot()
            hit_before = await self._get_hit_test_snapshot(lx, ly, selector=selector)

            # --- INTELLIGENT AUTO-SCROLL ---
            # Get current viewport height
            res_vh = await self._call_cdp("Runtime.evaluate", {"expression": "window.innerHeight", "returnByValue": True})
            vH = float(res_vh.get("result", {}).get("value", 800))

            auto_scrolled = False
            if ly > vH or ly < 0:
                logger.info(f"Target {ly} is off-screen (vH: {vH}). Performing Auto-Scroll & Recalibration...")
                # Scroll to target (centered better)
                scroll_y = ly - (vH / 2)
                await self._call_cdp("Runtime.evaluate", {"expression": f"window.scrollBy(0, {scroll_y})"})
                await asyncio.sleep(0.8) # Wait for scroll to settle
                # Recalibrate: Target is now at (original - scroll)
                ly = ly - scroll_y
                auto_scrolled = True
                # Note: lx remains same as we don't handle horizontal auto-scroll yet
            # -------------------------------

            if self.humanize_input_enabled:
                await self._human_click(lx, ly)
            else:
                # Fast-path click
                await self._call_cdp("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": lx, "y": ly, "button": "left", "clickCount": 1
                })
                await self._call_cdp("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": lx, "y": ly, "button": "left", "clickCount": 1
                })
                # Single sync update instead of many
                await self._update_cursor_overlay(lx, ly)

            await asyncio.sleep(0.05)
            after_mouse_probe = await self._get_mouse_probe_snapshot()
            after_focus = await self._get_runtime_focus_context()
            hit_after = await self._get_hit_test_snapshot(lx, ly, selector=selector)

            probe_delta = {
                "down": int(after_mouse_probe.get("down", 0)) - int(before_mouse_probe.get("down", 0)),
                "up": int(after_mouse_probe.get("up", 0)) - int(before_mouse_probe.get("up", 0)),
                "click": int(after_mouse_probe.get("click", 0)) - int(before_mouse_probe.get("click", 0)),
            }
            delivered = bool(probe_delta["down"] > 0 or probe_delta["up"] > 0 or probe_delta["click"] > 0)
            focus_changed = (
                str(before_focus.get("active_tag") or "") != str(after_focus.get("active_tag") or "")
                or str(before_focus.get("active_id") or "") != str(after_focus.get("active_id") or "")
                or bool(after_focus.get("is_editable", False)) != bool(before_focus.get("is_editable", False))
            )
            effect_observed = bool(delivered or focus_changed)
            
            evidence = await self._generate_evidence("", "", "click", {"x": lx, "y": ly}, target_bbox=BBox(x=lx-5, y=ly-5, width=10, height=10))
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="click",
                trace_id=self._trace_id,
                step_id="step_click",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=evidence,
                result_data={
                    "kind": "click_action_receipt_v1",
                    "selector": str(selector or ""),
                    "x": float(lx),
                    "y": float(ly),
                    "auto_scrolled": bool(auto_scrolled),
                    "delivered": bool(delivered),
                    "effect_observed": bool(effect_observed),
                    "probe_delta": probe_delta,
                    "focus_before": self._compact_for_log(before_focus),
                    "focus_after": self._compact_for_log(after_focus),
                    "hit_before": self._compact_for_log(hit_before),
                    "hit_after": self._compact_for_log(hit_after),
                },
            )
        except Exception as e:
            return self._error_response("click", str(e), start_time)
        finally:
            await self._set_agent_input_window(False)

    async def _get_mouse_probe_snapshot(self) -> Dict[str, Any]:
        expr = r"""
        (() => {
          const w = window;
          if (!w.__agentMouseProbeInstalled) {
            w.__agentMouseProbe = { down: 0, up: 0, click: 0, last_ts: 0, last_tag: "", last_id: "" };
            const mark = (kind, ev) => {
              try {
                const t = ev && ev.target ? ev.target : null;
                w.__agentMouseProbe[kind] = Number(w.__agentMouseProbe[kind] || 0) + 1;
                w.__agentMouseProbe.last_ts = Date.now();
                w.__agentMouseProbe.last_tag = String((t && t.tagName ? t.tagName : "") || "").toLowerCase();
                w.__agentMouseProbe.last_id = String((t && t.id ? t.id : "") || "");
              } catch (_) {}
            };
            window.addEventListener("mousedown", (ev) => mark("down", ev), true);
            window.addEventListener("mouseup", (ev) => mark("up", ev), true);
            window.addEventListener("click", (ev) => mark("click", ev), true);
            w.__agentMouseProbeInstalled = true;
          }
          const p = w.__agentMouseProbe || {};
          return {
            down: Number(p.down || 0),
            up: Number(p.up || 0),
            click: Number(p.click || 0),
            last_ts: Number(p.last_ts || 0),
            last_tag: String(p.last_tag || ""),
            last_id: String(p.last_id || ""),
          };
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    async def _get_hit_test_snapshot(
        self,
        x: float,
        y: float,
        selector: Optional[str] = None,
    ) -> Dict[str, Any]:
        selector_json = json.dumps(str(selector or ""))
        expr = f"""
        (() => {{
          const px = {float(x)};
          const py = {float(y)};
          const selector = {selector_json};
          const top = document.elementFromPoint(px, py);
          const interactive = top && (top.closest('a,button,input,select,textarea,option,[role="button"],[role="link"],[role="option"],[role="menuitem"],[onclick],[tabindex]') || null);
          const resolved = selector ? document.querySelector(selector) : null;
          const topStyle = top ? getComputedStyle(top) : null;
          const targetMatchesSelector = !!(resolved && top && (resolved === top || resolved.contains(top) || top.contains(resolved)));
          return {{
            x: px,
            y: py,
            top_tag: String((top && top.tagName ? top.tagName : "") || "").toLowerCase(),
            top_id: String((top && top.id ? top.id : "") || ""),
            top_role: String((top && top.getAttribute ? top.getAttribute("role") : "") || ""),
            top_text: String((top && top.innerText ? top.innerText : "") || "").slice(0, 120),
            pointer_events: String((topStyle && topStyle.pointerEvents ? topStyle.pointerEvents : "") || ""),
            visibility: String((topStyle && topStyle.visibility ? topStyle.visibility : "") || ""),
            has_interactive_ancestor: !!interactive,
            interactive_tag: String((interactive && interactive.tagName ? interactive.tagName : "") || "").toLowerCase(),
            interactive_id: String((interactive && interactive.id ? interactive.id : "") || ""),
            selector: String(selector || ""),
            target_matches_selector: targetMatchesSelector,
          }};
        }})()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    async def _focus_editable_by_point(self, x: float, y: float) -> Dict[str, Any]:
        expr = f"""
        (() => {{
          const px = {float(x)};
          const py = {float(y)};
          const direct = document.elementFromPoint(px, py);
          const editable = direct && (direct.closest('input, textarea, [contenteditable="true"], [contenteditable]') || direct);
          if (!editable) {{
            return {{ focused: false, reason: "no_element", x: px, y: py }};
          }}
          try {{ editable.focus(); }} catch (e) {{}}
          const isEditable = !!(
            editable.matches?.('input, textarea, [contenteditable="true"], [contenteditable]') ||
            editable.isContentEditable
          );
          return {{
            focused: document.activeElement === editable,
            is_editable: isEditable,
            tag: String((editable.tagName || "").toLowerCase()),
            id: String(editable.id || ""),
            name: String(editable.getAttribute?.("name") || ""),
            type: String(editable.getAttribute?.("type") || ""),
            x: px,
            y: py
          }};
        }})()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {"focused": False, "reason": "invalid_response"}
        except Exception as e:
            return {"focused": False, "reason": f"focus_eval_error: {e}"}

    async def _clear_focused_editable(self) -> bool:
        expr = r"""
        (() => {
          const el = document.activeElement;
          if (!el) return false;
          const tag = String(el.tagName || "").toLowerCase();
          const isInput = tag === "input" || tag === "textarea";
          const isEditable = isInput || el.isContentEditable;
          if (!isEditable) return false;
          if (isInput) {
            el.value = "";
          } else {
            el.textContent = "";
          }
          try { el.dispatchEvent(new Event("input", { bubbles: true })); } catch (e) {}
          try { el.dispatchEvent(new Event("change", { bubbles: true })); } catch (e) {}
          return true;
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return bool(res.get("result", {}).get("value", False))
        except Exception:
            return False

    async def _is_active_editable(self) -> bool:
        expr = """
        (() => {
          const el = document.activeElement;
          if (!el) return false;
          const tag = String(el.tagName || "").toLowerCase();
          const isInput = tag === "input" || tag === "textarea";
          return !!(isInput || el.isContentEditable);
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return bool(res.get("result", {}).get("value", False))
        except Exception:
            return False

    async def blur_active_editable(self) -> bool:
        expr = r"""
        (() => {
          const el = document.activeElement;
          if (!el) return false;
          const tag = String(el.tagName || "").toLowerCase();
          const editable = !!(
            tag === "input" || tag === "textarea" ||
            el.isContentEditable ||
            el.matches?.('[contenteditable="true"], [contenteditable]')
          );
          if (!editable) return false;
          try { el.blur(); } catch (e) {}
          return true;
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return bool(res.get("result", {}).get("value", False))
        except Exception:
            return False

    async def _get_runtime_focus_context(self) -> Dict[str, Any]:
        expr = r"""
        (() => {
          const el = document.activeElement;
          const tag = String(el?.tagName || "").toLowerCase();
          const role = String(el?.getAttribute?.("role") || "");
          const type = String(el?.getAttribute?.("type") || "");
          const name = String(el?.getAttribute?.("name") || "");
          const id = String(el?.id || "");
          const editable = !!(el && (
            el.matches?.('input, textarea, [contenteditable="true"], [contenteditable]') ||
            el.isContentEditable
          ));
          return {
            ready_state: String(document.readyState || ""),
            time_origin: Number((performance && performance.timeOrigin) || 0),
            active_tag: tag,
            active_role: role,
            active_type: type,
            active_name: name,
            active_id: id,
            is_editable: editable,
          };
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    async def _get_scroll_context(self) -> Dict[str, Any]:
        expr = r"""
        (() => ({
          x: Number(window.scrollX || window.pageXOffset || 0),
          y: Number(window.scrollY || window.pageYOffset || 0),
          inner_h: Number(window.innerHeight || 0),
          inner_w: Number(window.innerWidth || 0),
          doc_h: Number(
            Math.max(
              document.body?.scrollHeight || 0,
              document.documentElement?.scrollHeight || 0
            )
          ),
          doc_w: Number(
            Math.max(
              document.body?.scrollWidth || 0,
              document.documentElement?.scrollWidth || 0
            )
          ),
        }))()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    async def _get_key_probe_snapshot(self) -> Dict[str, Any]:
        expr = r"""
        (() => {
          const w = window;
          if (!w.__agentKeyProbeInstalled) {
            w.__agentKeyProbe = { down: 0, up: 0, char: 0, last_key: "", last_code: "", last_ts: 0 };
            const mark = (kind, ev) => {
              try {
                w.__agentKeyProbe[kind] = Number(w.__agentKeyProbe[kind] || 0) + 1;
                w.__agentKeyProbe.last_key = String(ev?.key || "");
                w.__agentKeyProbe.last_code = String(ev?.code || "");
                w.__agentKeyProbe.last_ts = Date.now();
              } catch (_) {}
            };
            window.addEventListener("keydown", (ev) => mark("down", ev), true);
            window.addEventListener("keyup", (ev) => mark("up", ev), true);
            window.addEventListener("keypress", (ev) => mark("char", ev), true);
            w.__agentKeyProbeInstalled = true;
          }
          const p = w.__agentKeyProbe || {};
          return {
            down: Number(p.down || 0),
            up: Number(p.up || 0),
            char: Number(p.char || 0),
            last_key: String(p.last_key || ""),
            last_code: String(p.last_code || ""),
            last_ts: Number(p.last_ts || 0),
          };
        })()
        """
        try:
            res = await self._call_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            value = res.get("result", {}).get("value", {})
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _modifier_mask(modifiers: Optional[List[str]]) -> int:
        if not isinstance(modifiers, list):
            return 0
        bit = 0
        for m in modifiers:
            v = str(m or "").strip().lower()
            if v in {"alt", "option"}:
                bit |= 1
            elif v in {"ctrl", "control"}:
                bit |= 2
            elif v in {"meta", "cmd", "command", "win", "windows"}:
                bit |= 4
            elif v in {"shift"}:
                bit |= 8
        return bit

    @staticmethod
    def _key_meta(key: str) -> Dict[str, Any]:
        k = str(key or "Enter")
        l = k.lower()
        special = {
            "enter": ("Enter", "Enter", 13, "\r"),
            "tab": ("Tab", "Tab", 9, "\t"),
            "escape": ("Escape", "Escape", 27, ""),
            "esc": ("Escape", "Escape", 27, ""),
            "arrowdown": ("ArrowDown", "ArrowDown", 40, ""),
            "arrowup": ("ArrowUp", "ArrowUp", 38, ""),
            "arrowleft": ("ArrowLeft", "ArrowLeft", 37, ""),
            "arrowright": ("ArrowRight", "ArrowRight", 39, ""),
            "pagedown": ("PageDown", "PageDown", 34, ""),
            "pageup": ("PageUp", "PageUp", 33, ""),
            "backspace": ("Backspace", "Backspace", 8, ""),
            "delete": ("Delete", "Delete", 46, ""),
        }
        if l in special:
            key_name, code, key_code, text = special[l]
            return {"key": key_name, "code": code, "key_code": key_code, "text": text}
        if len(k) == 1:
            up = k.upper()
            return {"key": k, "code": f"Key{up}" if up.isalpha() else k, "key_code": ord(up), "text": k}
        return {"key": k, "code": k, "key_code": 0, "text": ""}

    async def wait_after_action(
        self,
        before_context: Optional[Dict[str, Any]] = None,
        action: str = "",
        *,
        short_settle_s: float = 0.8,
        reload_settle_s: float = 0.6,
        load_timeout_s: float = 8.0,
    ) -> Dict[str, Any]:
        """
        Post-action execution gate:
        - If document context changed (timeOrigin), treat as reload/navigation and wait for load.
        - Otherwise, wait a short settle to avoid premature planner re-evaluation.
        """
        before_context = before_context if isinstance(before_context, dict) else {}
        before_origin = float(before_context.get("time_origin") or 0.0)
        after_context = await self._get_runtime_focus_context()
        after_origin = float(after_context.get("time_origin") or 0.0)
        reloaded = bool(before_origin and after_origin and abs(after_origin - before_origin) > 0.001)

        # Explicit navigate should always wait for load.
        if str(action or "").lower() == "navigate":
            reloaded = True

        if reloaded:
            await self._wait_for_load(timeout=max(1.0, float(load_timeout_s)))
            await asyncio.sleep(max(0.1, float(reload_settle_s)))
        else:
            await asyncio.sleep(max(0.1, float(short_settle_s)))

        final_context = await self._get_runtime_focus_context()
        logger.info(
            "action_gate %s",
            json.dumps(
                self._trace_ctx(
                    action=str(action or ""),
                    reloaded=str(bool(reloaded)),
                    before_origin=str(before_origin),
                    after_origin=str(after_origin),
                    final_ready_state=str(final_context.get("ready_state", "")),
                    focus_tag=str(final_context.get("active_tag", "")),
                ),
                ensure_ascii=False,
            ),
        )
        return {
            "reloaded": reloaded,
            "before": before_context,
            "after": final_context,
        }

    async def press_key(
        self,
        key: str = "Enter",
        modifiers: Optional[List[str]] = None,
        retries: int = 2,
    ) -> Dict[str, Any]:
        meta = self._key_meta(key)
        mask = self._modifier_mask(modifiers)
        before_focus = await self._get_runtime_focus_context()
        before_probe = await self._get_key_probe_snapshot()
        delivered = False
        attempts = 0
        last_probe_delta: Dict[str, int] = {"down": 0, "up": 0, "char": 0}

        for idx in range(max(1, int(retries))):
            attempts += 1
            down_type = "rawKeyDown" if (mask and idx == 0) else "keyDown"
            down_event: Dict[str, Any] = {
                "type": down_type,
                "key": meta["key"],
                "code": meta["code"],
                "windowsVirtualKeyCode": int(meta["key_code"]),
                "nativeVirtualKeyCode": int(meta["key_code"]),
                "modifiers": int(mask),
            }
            if meta.get("text") and not mask:
                down_event["text"] = meta["text"]
                down_event["unmodifiedText"] = meta["text"]
            up_event = {
                "type": "keyUp",
                "key": meta["key"],
                "code": meta["code"],
                "windowsVirtualKeyCode": int(meta["key_code"]),
                "nativeVirtualKeyCode": int(meta["key_code"]),
                "modifiers": int(mask),
            }

            await self._call_cdp("Input.dispatchKeyEvent", down_event)
            if meta.get("text") and not mask and len(str(meta["text"])) == 1:
                await self._call_cdp(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "char",
                        "text": meta["text"],
                        "unmodifiedText": meta["text"],
                        "key": meta["key"],
                        "code": meta["code"],
                        "windowsVirtualKeyCode": int(meta["key_code"]),
                        "nativeVirtualKeyCode": int(meta["key_code"]),
                        "modifiers": int(mask),
                    },
                )
            await self._call_cdp("Input.dispatchKeyEvent", up_event)
            await asyncio.sleep(0.04)

            after_probe = await self._get_key_probe_snapshot()
            last_probe_delta = {
                "down": int(after_probe.get("down", 0)) - int(before_probe.get("down", 0)),
                "up": int(after_probe.get("up", 0)) - int(before_probe.get("up", 0)),
                "char": int(after_probe.get("char", 0)) - int(before_probe.get("char", 0)),
            }
            delivered = (last_probe_delta["down"] > 0) or (last_probe_delta["up"] > 0)
            if delivered:
                break

        after_focus = await self._get_runtime_focus_context()
        focus_editable = bool(before_focus.get("is_editable", False) or after_focus.get("is_editable", False))
        accepted = bool(delivered and (key.lower() != "enter" or focus_editable))
        receipt = {
            "kind": "key_event_receipt_v1",
            "key": str(meta["key"]),
            "code": str(meta["code"]),
            "modifiers": list(modifiers or []),
            "modifier_mask": int(mask),
            "attempts": attempts,
            "dispatched": True,
            "delivered": bool(delivered),
            "accepted": bool(accepted),
            "focus_editable": bool(focus_editable),
            "probe_delta": last_probe_delta,
            "focus_before": self._compact_for_log(before_focus),
            "focus_after": self._compact_for_log(after_focus),
        }
        logger.info(
            "press_key.receipt %s",
            json.dumps(self._trace_ctx(receipt=json.dumps(self._compact_for_log(receipt), ensure_ascii=False)), ensure_ascii=False),
        )
        return receipt

    async def type_text(
        self,
        text: str,
        selector: Optional[str] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        press_enter: bool = False,
        focus_before_type: bool = True,
        clear_existing: bool = False,
    ) -> ToonResponse:
        start_time = time.time()
        try:
            await self._ensure_control_overlay()
            await self._set_agent_input_window(True)
            pre_focus = await self._get_runtime_focus_context()
            focus_meta: Dict[str, Any] = {}
            logger.info(
                "type_text.start %s",
                json.dumps(
                    self._trace_ctx(
                        text_len=str(len(str(text or ""))),
                        selector=str(selector or ""),
                        x=str(x if x is not None else ""),
                        y=str(y if y is not None else ""),
                        press_enter=str(bool(press_enter)),
                        focus_before_type=str(bool(focus_before_type)),
                        clear_existing=str(bool(clear_existing)),
                    ),
                    ensure_ascii=False,
                ),
            )
            if focus_before_type:
                if selector:
                    await self.click(selector=selector)
                elif x is not None and y is not None:
                    await self.click(x=float(x), y=float(y))
                    focus_meta = await self._focus_editable_by_point(float(x), float(y))
                    logger.info(
                        "type_text.focus %s",
                        json.dumps(
                            self._trace_ctx(focus=json.dumps(self._compact_for_log(focus_meta), ensure_ascii=False)),
                            ensure_ascii=False,
                        ),
                    )
                # click() resets agent_input in its own finally block.
                # Re-enable it so overlay lock does not block typed keys.
                await self._set_agent_input_window(True)
            active_editable_before_insert = await self._is_active_editable()
            if not active_editable_before_insert:
                return self._error_response("type", "active element not editable before insertText", start_time)
            if clear_existing:
                cleared = await self._clear_focused_editable()
                logger.info(
                    "type_text.clear %s",
                    json.dumps(self._trace_ctx(cleared=str(bool(cleared))), ensure_ascii=False),
                )
                if not cleared:
                    editable_now = await self._is_active_editable()
                    if editable_now:
                        await self._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "windowsVirtualKeyCode": 65, "key": "a"})
                        await self._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "windowsVirtualKeyCode": 65, "key": "a"})
                        await self._call_cdp("Input.dispatchKeyEvent", {"type": "keyDown", "windowsVirtualKeyCode": 8, "key": "Backspace"})
                        await self._call_cdp("Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 8, "key": "Backspace"})
                    else:
                        logger.warning(
                            "type_text.clear.skip_ctrl_a %s",
                            json.dumps(self._trace_ctx(reason="active_element_not_editable"), ensure_ascii=False),
                        )
            
            if self.humanize_input_enabled:
                for char in text:
                    await self._call_cdp("Input.insertText", {"text": char})
                    await asyncio.sleep(random.uniform(0.02, 0.08))
            else:
                await self._call_cdp("Input.insertText", {"text": str(text or "")})

            enter_dispatched = False
            key_receipt: Dict[str, Any] = {}
            if press_enter:
                key_receipt = await self.press_key("Enter")
                enter_dispatched = bool(key_receipt.get("accepted", False))

            post_focus = await self._get_runtime_focus_context()
            receipt = {
                "kind": "type_action_receipt_v1",
                "text_len": int(len(str(text or ""))),
                "press_enter": bool(press_enter),
                "enter_dispatched": bool(enter_dispatched),
                "focus_before": self._compact_for_log(pre_focus),
                "focus_after": self._compact_for_log(post_focus),
                "focus_click_meta": self._compact_for_log(focus_meta),
                "clear_existing": bool(clear_existing),
                "key_receipt": self._compact_for_log(key_receipt),
                "active_editable_before_insert": bool(active_editable_before_insert),
            }
            logger.info(
                "type_text.receipt %s",
                json.dumps(self._trace_ctx(receipt=json.dumps(self._compact_for_log(receipt), ensure_ascii=False)), ensure_ascii=False),
            )
            
            return ToonResponse(
                command_id=f"cmd_{int(time.time())}",
                component="runtime",
                action="type",
                trace_id=self._trace_id,
                step_id="step_type",
                status="success",
                execution_time=time.time() - start_time,
                evidence_pack=await self._generate_evidence("", "", "type", {"text": text}),
                result_data=receipt,
            )
        except Exception as e:
            return self._error_response("type", str(e), start_time)
        finally:
            await self._set_agent_input_window(False)

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
            await self._ensure_control_overlay()
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

    async def scroll_page(self, pixels: int) -> Dict[str, Any]:
        before_focus = await self._get_runtime_focus_context()
        before_scroll = await self._get_scroll_context()
        await self._call_cdp("Runtime.evaluate", {"expression": f"window.scrollBy(0, {int(pixels)})"})
        await asyncio.sleep(0.25)
        after_focus = await self._get_runtime_focus_context()
        after_scroll = await self._get_scroll_context()
        before_y = float(before_scroll.get("y") or 0.0)
        after_y = float(after_scroll.get("y") or 0.0)
        delta_y = after_y - before_y
        return {
            "kind": "scroll_action_receipt_v1",
            "requested_pixels": int(pixels),
            "before_y": before_y,
            "after_y": after_y,
            "delta_y": delta_y,
            "delivered": bool(abs(delta_y) >= 4.0),
            "focus_before": self._compact_for_log(before_focus),
            "focus_after": self._compact_for_log(after_focus),
        }

    async def mouse_move(self, x: float, y: float) -> ToonResponse:
        start_time = time.time()
        try:
            await self._ensure_control_overlay()
            await self._set_agent_input_window(True)
            if self.humanize_input_enabled:
                await self._human_move_to(float(x), float(y))
            else:
                await self._call_cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
                await self._update_cursor_overlay(float(x), float(y))
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
        finally:
            await self._set_agent_input_window(False)

    async def wait(self, seconds: float) -> ToonResponse:
        start_time = time.time()
        await self._ensure_control_overlay()
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
