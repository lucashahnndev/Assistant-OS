from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import MCPServerConfig


class MCPServerRegistry:
    def __init__(self):
        self._servers: Dict[str, MCPServerConfig] = {}

    def load_from_config(self, raw_config: Dict[str, Any]) -> None:
        self._servers = {}
        config = raw_config if isinstance(raw_config, dict) else {}
        for item in list(config.get("servers") or []):
            server = MCPServerConfig.model_validate(item)
            self.register(server)

    def register(self, server: MCPServerConfig) -> None:
        self._servers[server.id] = server

    def get(self, server_id: str) -> Optional[MCPServerConfig]:
        return self._servers.get(str(server_id or "").strip().lower())

    def list_all(self) -> List[MCPServerConfig]:
        return [self._servers[key] for key in sorted(self._servers.keys())]

    def list_enabled(self) -> List[MCPServerConfig]:
        return [server for server in self.list_all() if bool(server.enabled)]

    def is_tool_allowed(self, server_id: str, tool_name: str) -> bool:
        server = self.get(server_id)
        if server is None or not server.enabled:
            return False
        tool = str(tool_name or "").strip()
        if not tool:
            return False
        if tool in set(server.policy.tool_denylist or []):
            return False
        allowlist = list(server.policy.tool_allowlist or [])
        if allowlist and tool not in set(allowlist):
            return False
        return True
