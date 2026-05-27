from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from capabilities.base import CapabilityBase
from capabilities.registry import CapabilityRegistry
from capabilities.shared.error_contract import elapsed_ms, error_envelope, now_perf, success_envelope
from utils.logging_config import get_logger

from .bridge import MCPToolAdapter
from .client import MCPClientManager
from .models import MCPActionDescriptor, MCPResourceDescriptor, MCPServerConfig
from .registry import MCPServerRegistry

logger = get_logger("MCPIntegrationService")


class MCPDynamicCapability(CapabilityBase):
    def __init__(
        self,
        *,
        client_manager: MCPClientManager,
        server_by_action: Dict[str, MCPServerConfig],
        descriptor_by_action: Dict[str, MCPActionDescriptor],
        resource_catalog: Dict[str, Dict[str, MCPResourceDescriptor]],
    ):
        self._client_manager = client_manager
        self._server_by_action = server_by_action
        self._descriptor_by_action = descriptor_by_action
        self._resource_catalog = resource_catalog

    @property
    def name(self) -> str:
        return "mcp_dynamic_bridge"

    @property
    def actions(self) -> List[str]:
        return sorted(self._descriptor_by_action.keys())

    def replace_actions(
        self,
        *,
        server_by_action: Dict[str, MCPServerConfig],
        descriptor_by_action: Dict[str, MCPActionDescriptor],
        resource_catalog: Dict[str, Dict[str, MCPResourceDescriptor]],
    ) -> None:
        self._server_by_action = server_by_action
        self._descriptor_by_action = descriptor_by_action
        self._resource_catalog = resource_catalog

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        _ = context
        started = now_perf()
        descriptor = self._descriptor_by_action.get(str(action_id or "").strip())
        if descriptor is None:
            return error_envelope(
                provider="mcp_dynamic_bridge",
                error_code="UNKNOWN_MCP_ACTION",
                error_message=f"Unknown MCP action: {action_id}",
                retryable=False,
                elapsed=elapsed_ms(started),
            )
        server = self._server_by_action.get(descriptor.action_id)
        if server is None:
            return error_envelope(
                provider="mcp_dynamic_bridge",
                error_code="MCP_SERVER_NOT_AVAILABLE",
                error_message=f"MCP server not available for action: {descriptor.action_id}",
                retryable=True,
                elapsed=elapsed_ms(started),
            )
        try:
            kind = str(descriptor.metadata.get("kind") or "tool.call").strip().lower()
            if kind == "resource.read":
                uri = str((params or {}).get("uri") or "").strip()
                if not uri:
                    return error_envelope(
                        provider=f"mcp:{server.id}",
                        error_code="MCP_RESOURCE_URI_REQUIRED",
                        error_message="Missing MCP resource uri.",
                        retryable=False,
                        elapsed=elapsed_ms(started),
                    )
                payload = self._client_manager.read_resource(server, uri)
            else:
                payload = self._client_manager.invoke_tool(server, descriptor.tool_name, params or {})
        except Exception as exc:
            logger.warning(
                "MCP action invocation failed | action=%s server=%s error=%s",
                descriptor.action_id,
                server.id,
                exc,
            )
            return error_envelope(
                provider=f"mcp:{server.id}",
                error_code="MCP_TOOL_EXECUTION_ERROR",
                error_message=str(exc),
                retryable=True,
                elapsed=elapsed_ms(started),
            )

        response = success_envelope(provider=f"mcp:{server.id}", elapsed=elapsed_ms(started))
        response["data"] = {
            "resource_result": payload if str(descriptor.metadata.get("kind") or "") == "resource.read" else None,
            "tool_result": payload if str(descriptor.metadata.get("kind") or "") != "resource.read" else None,
        }
        response["metadata"] = {
            "origin": "mcp",
            "action_id": descriptor.action_id,
            "tool_name": descriptor.tool_name,
            "server_id": server.id,
            "read_only": descriptor.read_only,
        }
        return response


class MCPIntegrationService:
    def __init__(
        self,
        *,
        config_manager: Any,
        capability_registry: CapabilityRegistry,
        client_manager: Optional[MCPClientManager] = None,
        server_registry: Optional[MCPServerRegistry] = None,
        tool_adapter: Optional[MCPToolAdapter] = None,
    ):
        self.config_manager = config_manager
        self.capability_registry = capability_registry
        self.client_manager = client_manager or MCPClientManager()
        self.server_registry = server_registry or MCPServerRegistry()
        self.tool_adapter = tool_adapter or MCPToolAdapter()
        self._dynamic_capability = MCPDynamicCapability(
            client_manager=self.client_manager,
            server_by_action={},
            descriptor_by_action={},
            resource_catalog={},
        )
        self._source_id = "mcp.dynamic"
        self.last_refresh_stats: Dict[str, Any] = {}
        self.resource_catalog_by_server: Dict[str, Dict[str, MCPResourceDescriptor]] = {}

    @staticmethod
    def _build_resource_read_action_id(server: MCPServerConfig) -> str:
        namespace = str(server.policy.namespace or "mcp").strip().lower()
        return f"{namespace}.{server.id}.read_resource"

    def refresh(self) -> Dict[str, Any]:
        raw_cfg = self.config_manager.get_mcp_config() if hasattr(self.config_manager, "get_mcp_config") else {}
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        if not bool(cfg.get("enabled", False)):
            self.capability_registry.unregister_dynamic_actions(self._source_id)
            self._dynamic_capability.replace_actions(server_by_action={}, descriptor_by_action={}, resource_catalog={})
            self.resource_catalog_by_server = {}
            self.last_refresh_stats = {"enabled": False, "registered_actions": 0, "servers_considered": 0}
            return dict(self.last_refresh_stats)

        self.server_registry.load_from_config(cfg)
        actions_payload: List[Dict[str, Any]] = []
        server_by_action: Dict[str, MCPServerConfig] = {}
        descriptor_by_action: Dict[str, MCPActionDescriptor] = {}
        resource_catalog_by_server: Dict[str, Dict[str, MCPResourceDescriptor]] = {}
        servers_considered = 0
        errors: List[str] = []

        for server in self.server_registry.list_enabled():
            servers_considered += 1
            if not bool(server.policy.allow_tool_discovery):
                continue
            try:
                tools = list(self.client_manager.list_tools(server) or [])
            except Exception as exc:
                logger.warning("MCP discovery failed | server=%s error=%s", server.id, exc)
                errors.append(f"{server.id}:tool_discovery_failed:{exc}")
                continue
            for descriptor in self.tool_adapter.build_action_descriptors(server, tools):
                descriptor_by_action[descriptor.action_id] = descriptor
                server_by_action[descriptor.action_id] = server
                actions_payload.append(
                    {
                        "action_id": descriptor.action_id,
                        "title": descriptor.title,
                        "description": descriptor.description,
                        "handler": descriptor.tool_name,
                        "risk_level": descriptor.risk_level,
                        "permissions": {
                            "scopes": ["mcp.execute"],
                            "allow_anyone": True,
                            "requires_approval": descriptor.requires_approval,
                        },
                        "parameters": descriptor.parameters,
                        "side_effect": "none" if descriptor.read_only else "mutation",
                        "capability_id": f"mcp.{server.id}",
                        "capability_name": self._dynamic_capability.name,
                        "namespace": ".".join(descriptor.action_id.split(".")[:-1]),
                        "metadata": {
                            **descriptor.metadata,
                            "title": descriptor.title,
                            "description": descriptor.description,
                            "handler": descriptor.tool_name,
                            "risk_level": descriptor.risk_level,
                            "permissions": {
                                "scopes": ["mcp.execute"],
                                "allow_anyone": True,
                                "requires_approval": descriptor.requires_approval,
                            },
                            "parameters": descriptor.parameters,
                            "side_effect": "none" if descriptor.read_only else "mutation",
                            "capability_id": f"mcp.{server.id}",
                            "capability": self._dynamic_capability.name,
                        },
                    }
                )
            if bool(server.policy.allow_resources):
                try:
                    resources = list(self.client_manager.list_resources(server) or [])
                except Exception as exc:
                    logger.warning("MCP resources discovery failed | server=%s error=%s", server.id, exc)
                    errors.append(f"{server.id}:resources_discovery_failed:{exc}")
                    resources = []
                if resources:
                    resource_catalog_by_server[server.id] = {resource.uri: resource for resource in resources}
                    action_id = self._build_resource_read_action_id(server)
                    descriptor = MCPActionDescriptor(
                        action_id=action_id,
                        server_id=server.id,
                        tool_name="",
                        title=f"Read Resource ({server.title})",
                        description=f"Read a discovered MCP resource from {server.title}.",
                        parameters={
                            "type": "object",
                            "properties": {
                                "uri": {
                                    "type": "string",
                                    "enum": [resource.uri for resource in resources],
                                }
                            },
                            "required": ["uri"],
                            "additionalProperties": False,
                        },
                        risk_level="low",
                        requires_approval=False,
                        read_only=True,
                        metadata={
                            "origin": "mcp",
                            "server_id": server.id,
                            "kind": "resource.read",
                            "transport": server.transport.kind,
                            "trust_tier": server.policy.trust_tier,
                            "resource_uris": [resource.uri for resource in resources],
                        },
                    )
                    descriptor_by_action[action_id] = descriptor
                    server_by_action[action_id] = server
                    actions_payload.append(
                        {
                            "action_id": descriptor.action_id,
                            "title": descriptor.title,
                            "description": descriptor.description,
                            "handler": "resource.read",
                            "risk_level": descriptor.risk_level,
                            "permissions": {
                                "scopes": ["mcp.read"],
                                "allow_anyone": True,
                                "requires_approval": False,
                            },
                            "parameters": descriptor.parameters,
                            "side_effect": "none",
                            "capability_id": f"mcp.{server.id}",
                            "capability_name": self._dynamic_capability.name,
                            "namespace": ".".join(descriptor.action_id.split(".")[:-1]),
                            "metadata": {
                                **descriptor.metadata,
                                "title": descriptor.title,
                                "description": descriptor.description,
                                "handler": "resource.read",
                                "risk_level": descriptor.risk_level,
                                "permissions": {
                                    "scopes": ["mcp.read"],
                                    "allow_anyone": True,
                                    "requires_approval": False,
                                },
                                "parameters": descriptor.parameters,
                                "side_effect": "none",
                                "capability_id": f"mcp.{server.id}",
                                "capability": self._dynamic_capability.name,
                            },
                        }
                    )

        self._dynamic_capability.replace_actions(
            server_by_action=server_by_action,
            descriptor_by_action=descriptor_by_action,
            resource_catalog=resource_catalog_by_server,
        )
        self.resource_catalog_by_server = resource_catalog_by_server
        self.capability_registry.register_dynamic_actions(
            source_id=self._source_id,
            capability=self._dynamic_capability,
            actions=actions_payload,
        )
        self.last_refresh_stats = {
            "enabled": True,
            "registered_actions": len(actions_payload),
            "servers_considered": servers_considered,
            "servers_with_resources": len(resource_catalog_by_server),
            "errors": errors,
        }
        return dict(self.last_refresh_stats)

    def list_discovered_resources(self, server_id: str = "") -> List[Dict[str, Any]]:
        if server_id:
            resources = self.resource_catalog_by_server.get(str(server_id or "").strip().lower(), {})
            return [self._resource_row(str(server_id or "").strip().lower(), item) for item in resources.values()]
        rows: List[Dict[str, Any]] = []
        for sid, resources in self.resource_catalog_by_server.items():
            rows.extend([self._resource_row(sid, item) for item in resources.values()])
        return rows

    def retrieve_resources(
        self,
        *,
        query: str,
        max_results: int = 3,
    ) -> List[Dict[str, Any]]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        ranked: List[tuple[float, str, MCPResourceDescriptor]] = []
        for server_id, resources in self.resource_catalog_by_server.items():
            for resource in resources.values():
                score = self._resource_match_score(query_tokens=query_tokens, resource=resource)
                if score <= 0:
                    continue
                ranked.append((score, server_id, resource))

        ranked.sort(key=lambda row: (-row[0], row[1], row[2].uri))
        items: List[Dict[str, Any]] = []
        for score, server_id, resource in ranked[: max(1, int(max_results or 1))]:
            server = self.server_registry.get(server_id)
            if server is None:
                continue
            try:
                payload = self.client_manager.read_resource(server, resource.uri)
            except Exception as exc:
                logger.warning("MCP resource read failed | server=%s uri=%s error=%s", server_id, resource.uri, exc)
                continue
            content = self._resource_payload_to_text(payload)
            if not content:
                continue
            items.append(
                {
                    "title": resource.normalized_title(),
                    "content": content,
                    "source": resource.uri,
                    "metadata": {
                        "origin": "mcp_resource",
                        "server_id": server_id,
                        "resource_uri": resource.uri,
                        "mime_type": resource.mime_type,
                        "trust_level": "partner" if str(server.policy.trust_tier) == "partner" else str(server.policy.trust_tier or "medium"),
                        "knowledge_scope": "workspace",
                    },
                    "score": round(score, 4),
                    "provenance": [f"mcp:{server_id}", resource.uri],
                }
            )
        return items

    @staticmethod
    def _resource_row(server_id: str, resource: MCPResourceDescriptor) -> Dict[str, Any]:
        return {
            "server_id": server_id,
            "uri": resource.uri,
            "name": resource.name,
            "title": resource.normalized_title(),
            "description": resource.description,
            "mime_type": resource.mime_type,
        }

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [token for token in re.findall(r"[a-zA-Z0-9_]+", str(text or "").lower()) if len(token) > 1]

    def _resource_match_score(self, *, query_tokens: List[str], resource: MCPResourceDescriptor) -> float:
        haystack = " ".join(
            [
                str(resource.uri or ""),
                str(resource.name or ""),
                str(resource.title or ""),
                str(resource.description or ""),
            ]
        ).lower()
        if not haystack:
            return 0.0
        overlap = sum(1 for token in set(query_tokens) if token in haystack)
        if overlap <= 0:
            return 0.0
        return overlap / max(1, len(set(query_tokens)))

    @staticmethod
    def _resource_payload_to_text(payload: Dict[str, Any]) -> str:
        contents = payload.get("contents") if isinstance(payload.get("contents"), list) else []
        chunks: List[str] = []
        for item in contents:
            if not isinstance(item, dict):
                continue
            if str(item.get("text") or "").strip():
                chunks.append(str(item.get("text") or "").strip())
                continue
            if str(item.get("content") or "").strip():
                chunks.append(str(item.get("content") or "").strip())
        return " ".join(chunks).strip()
