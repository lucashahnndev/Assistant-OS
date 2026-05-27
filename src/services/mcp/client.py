from __future__ import annotations

from typing import Any, Callable, Dict, List, Protocol

from .models import MCPResourceDescriptor, MCPServerConfig, MCPToolDescriptor
from .transports import MCPHTTPTransportClient, MCPStdioTransportClient


class MCPTransportClient(Protocol):
    def list_tools(self) -> List[MCPToolDescriptor]:
        raise NotImplementedError

    def invoke_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def list_resources(self) -> List[MCPResourceDescriptor]:
        raise NotImplementedError

    def read_resource(self, resource_uri: str) -> Dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class MCPClientManager:
    def __init__(self):
        self._factories: Dict[str, Callable[[MCPServerConfig], MCPTransportClient]] = {
            "http": lambda server: MCPHTTPTransportClient(server),
            "stdio": lambda server: MCPStdioTransportClient(server),
        }
        self._clients: Dict[str, MCPTransportClient] = {}

    def register_factory(self, transport_kind: str, factory: Callable[[MCPServerConfig], MCPTransportClient]) -> None:
        self._factories[str(transport_kind or "").strip().lower()] = factory

    def connect(self, server: MCPServerConfig) -> MCPTransportClient:
        cached = self._clients.get(server.id)
        if cached is not None:
            return cached
        kind = str(server.transport.kind or "").strip().lower()
        factory = self._factories.get(kind)
        if factory is None:
            raise ValueError(f"unsupported mcp transport: {kind}")
        client = factory(server)
        self._clients[server.id] = client
        return client

    def list_tools(self, server: MCPServerConfig) -> List[MCPToolDescriptor]:
        return list(self.connect(server).list_tools() or [])

    def invoke_tool(self, server: MCPServerConfig, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        payload = arguments if isinstance(arguments, dict) else {}
        return dict(self.connect(server).invoke_tool(tool_name, payload) or {})

    def list_resources(self, server: MCPServerConfig) -> List[MCPResourceDescriptor]:
        return list(self.connect(server).list_resources() or [])

    def read_resource(self, server: MCPServerConfig, resource_uri: str) -> Dict[str, Any]:
        return dict(self.connect(server).read_resource(resource_uri) or {})

    def close(self, server_id: str) -> None:
        server_key = str(server_id or "").strip().lower()
        client = self._clients.pop(server_key, None)
        if client is None:
            return
        client.close()

    def close_all(self) -> None:
        for server_id in list(self._clients.keys()):
            self.close(server_id)
