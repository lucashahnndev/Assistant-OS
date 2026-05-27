from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import requests

from .models import MCPResourceDescriptor, MCPServerConfig, MCPToolDescriptor


class MCPHTTPTransportClient:
    def __init__(self, server: MCPServerConfig):
        self.server = server
        self.timeout_s = float(max(1.0, server.transport.startup_timeout_s))
        self.session = requests.Session()
        self._session_id = ""
        self._initialized = False
        self._jsonrpc_id = 0
        headers = {
            str(key): str(value)
            for key, value in (server.transport.headers or {}).items()
            if str(key).strip()
        }
        if headers:
            self.session.headers.update(headers)

    def list_tools(self) -> List[MCPToolDescriptor]:
        result = self._jsonrpc_call("tools/list", {})
        tools = result.get("tools") if isinstance(result.get("tools"), list) else []
        return [self._coerce_tool_descriptor(item) for item in tools if isinstance(item, dict)]

    def invoke_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._jsonrpc_call(
            "tools/call",
            {
                "name": str(tool_name or "").strip(),
                "arguments": dict(arguments or {}),
            },
        )

    def list_resources(self) -> List[MCPResourceDescriptor]:
        result = self._jsonrpc_call("resources/list", {})
        resources = result.get("resources") if isinstance(result.get("resources"), list) else []
        return [self._coerce_resource_descriptor(item) for item in resources if isinstance(item, dict)]

    def read_resource(self, resource_uri: str) -> Dict[str, Any]:
        return self._jsonrpc_call(
            "resources/read",
            {
                "uri": str(resource_uri or "").strip(),
            },
        )

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    def _jsonrpc_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_initialized()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": str(method or "").strip(),
            "params": dict(params or {}),
        }
        headers = self._request_headers()
        response = self.session.post(
            self._endpoint(),
            json=payload,
            headers=headers,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        data = self._decode_payload(response.text)
        if isinstance(data.get("error"), dict):
            raise RuntimeError(str(data["error"].get("message") or "MCP HTTP error"))
        result = data.get("result")
        return result if isinstance(result, dict) else {}

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "assistant-os", "version": "1.0"},
            },
        }
        response = self.session.post(
            self._endpoint(),
            json=payload,
            headers=self._request_headers(include_session=False),
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        data = self._decode_payload(response.text)
        if isinstance(data.get("error"), dict):
            raise RuntimeError(str(data["error"].get("message") or "MCP initialize error"))
        self._session_id = str(
            response.headers.get("mcp-session-id", "") or response.headers.get("Mcp-Session-Id", "") or ""
        ).strip()
        notify_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        notify_response = self.session.post(
            self._endpoint(),
            json=notify_payload,
            headers=self._request_headers(),
            timeout=self.timeout_s,
        )
        notify_response.raise_for_status()
        self._initialized = True

    def _request_headers(self, *, include_session: bool = True) -> Dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if include_session and self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _endpoint(self) -> str:
        raw = self._canonicalize_endpoint(str(self.server.transport.endpoint or "").strip()).rstrip("/")
        if not raw:
            raise RuntimeError(f"MCP server '{self.server.id}' missing endpoint")
        parsed = urlparse(raw)
        if parsed.path.endswith("/mcp"):
            return raw
        if parsed.path.endswith("/tools/call"):
            return raw
        return raw + "/mcp"

    def _next_id(self) -> int:
        self._jsonrpc_id += 1
        return self._jsonrpc_id

    @staticmethod
    def _canonicalize_endpoint(raw_endpoint: str) -> str:
        raw = str(raw_endpoint or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").strip().lower()
        if host == "127.0.0.1":
            auth = ""
            if parsed.username:
                auth = parsed.username
                if parsed.password:
                    auth += f":{parsed.password}"
                auth += "@"
            port = f":{parsed.port}" if parsed.port else ""
            parsed = parsed._replace(netloc=f"{auth}localhost{port}")
            return urlunparse(parsed)
        return raw

    @staticmethod
    def _decode_payload(raw_text: str) -> Dict[str, Any]:
        raw = str(raw_text or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        data_lines: List[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("data:"):
                data_lines.append(stripped[len("data:") :].strip())
        if not data_lines:
            raise RuntimeError("Invalid MCP HTTP payload")
        parsed = json.loads("\n".join(data_lines))
        if not isinstance(parsed, dict):
            raise RuntimeError("Invalid MCP SSE payload object")
        return parsed

    @staticmethod
    def _coerce_tool_descriptor(item: Dict[str, Any]) -> MCPToolDescriptor:
        return MCPToolDescriptor.model_validate(
            {
                "name": item.get("name"),
                "title": item.get("title") or "",
                "description": item.get("description") or "",
                "input_schema": item.get("inputSchema") or item.get("input_schema") or {},
                "annotations": item.get("annotations") or {},
            }
        )

    @staticmethod
    def _coerce_resource_descriptor(item: Dict[str, Any]) -> MCPResourceDescriptor:
        return MCPResourceDescriptor.model_validate(
            {
                "uri": item.get("uri"),
                "name": item.get("name") or "",
                "title": item.get("title") or "",
                "description": item.get("description") or "",
                "mime_type": item.get("mimeType") or item.get("mime_type") or "",
            }
        )


class MCPStdioTransportClient:
    def __init__(self, server: MCPServerConfig):
        self.server = server
        self.timeout_s = float(max(1.0, server.transport.startup_timeout_s))
        self._jsonrpc_id = 0
        self._proc: Optional[subprocess.Popen] = None
        self._initialized = False

    def list_tools(self) -> List[MCPToolDescriptor]:
        result = self._jsonrpc_call("tools/list", {})
        tools = result.get("tools") if isinstance(result.get("tools"), list) else []
        return [MCPHTTPTransportClient._coerce_tool_descriptor(item) for item in tools if isinstance(item, dict)]

    def invoke_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._jsonrpc_call(
            "tools/call",
            {
                "name": str(tool_name or "").strip(),
                "arguments": dict(arguments or {}),
            },
        )

    def list_resources(self) -> List[MCPResourceDescriptor]:
        result = self._jsonrpc_call("resources/list", {})
        resources = result.get("resources") if isinstance(result.get("resources"), list) else []
        return [MCPHTTPTransportClient._coerce_resource_descriptor(item) for item in resources if isinstance(item, dict)]

    def read_resource(self, resource_uri: str) -> Dict[str, Any]:
        return self._jsonrpc_call(
            "resources/read",
            {
                "uri": str(resource_uri or "").strip(),
            },
        )

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _jsonrpc_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_initialized()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": str(method or "").strip(),
            "params": dict(params or {}),
        }
        response = self._send_request(payload)
        if isinstance(response.get("error"), dict):
            raise RuntimeError(str(response["error"].get("message") or "MCP stdio error"))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._ensure_process()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "assistant-os", "version": "1.0"},
            },
        }
        response = self._send_request(payload)
        if isinstance(response.get("error"), dict):
            raise RuntimeError(str(response["error"].get("message") or "MCP initialize error"))
        self._send_notification({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self._initialized = True

    def _ensure_process(self) -> None:
        if self._proc is not None:
            return
        command = str(self.server.transport.command or "").strip()
        if not command:
            raise RuntimeError(f"MCP server '{self.server.id}' missing stdio command")
        args = shlex.split(command)
        if self.server.transport.args:
            args.extend([str(arg) for arg in self.server.transport.args])
        env = None
        if self.server.transport.env:
            import os

            env = dict(os.environ)
            env.update({str(k): str(v) for k, v in self.server.transport.env.items()})
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )

    def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_process()
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("MCP stdio process unavailable")
        serialized = json.dumps(payload, separators=(",", ":"))
        proc.stdin.write(serialized + "\n")
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                stderr_text = ""
                if proc.stderr is not None:
                    try:
                        stderr_text = proc.stderr.read()[:500]
                    except Exception:
                        stderr_text = ""
                raise RuntimeError(f"MCP stdio server closed unexpectedly. {stderr_text}".strip())
            text = str(line or "").strip()
            if not text:
                continue
            data = json.loads(text)
            if isinstance(data, dict) and data.get("id") == payload.get("id"):
                return data

    def _send_notification(self, payload: Dict[str, Any]) -> None:
        self._ensure_process()
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("MCP stdio process unavailable")
        serialized = json.dumps(payload, separators=(",", ":"))
        proc.stdin.write(serialized + "\n")
        proc.stdin.flush()

    def _next_id(self) -> int:
        self._jsonrpc_id += 1
        return self._jsonrpc_id
