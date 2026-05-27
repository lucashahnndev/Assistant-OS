from __future__ import annotations

from typing import Dict, List

from .models import MCPActionDescriptor, MCPServerConfig, MCPToolDescriptor, slugify_action_token
from .policy import MCPPolicyGate


class MCPToolAdapter:
    def __init__(self, policy_gate: MCPPolicyGate | None = None):
        self.policy_gate = policy_gate or MCPPolicyGate()

    def build_action_id(self, server: MCPServerConfig, tool: MCPToolDescriptor) -> str:
        namespace = str(server.policy.namespace or "mcp").strip().lower()
        server_token = slugify_action_token(server.id)
        tool_token = slugify_action_token(tool.name)
        return f"{namespace}.{server_token}.{tool_token}"

    def build_action_descriptor(self, server: MCPServerConfig, tool: MCPToolDescriptor) -> MCPActionDescriptor | None:
        decision = self.policy_gate.evaluate_tool(server, tool)
        if not decision.allowed:
            return None
        return MCPActionDescriptor(
            action_id=self.build_action_id(server, tool),
            server_id=server.id,
            tool_name=tool.name,
            title=tool.normalized_title(),
            description=str(tool.description or "").strip() or f"MCP tool {tool.name} exposed by {server.title}.",
            parameters=dict(tool.input_schema or {"type": "object", "properties": {}}),
            risk_level=decision.risk_level,
            requires_approval=decision.requires_approval,
            read_only=decision.read_only,
            metadata={
                "origin": "mcp",
                "server_id": server.id,
                "tool_name": tool.name,
                "transport": server.transport.kind,
                "trust_tier": server.policy.trust_tier,
                "read_only": decision.read_only,
                "destructive": decision.destructive,
            },
        )

    def build_action_descriptors(
        self,
        server: MCPServerConfig,
        tools: List[MCPToolDescriptor],
    ) -> List[MCPActionDescriptor]:
        actions: List[MCPActionDescriptor] = []
        for tool in tools or []:
            descriptor = self.build_action_descriptor(server, tool)
            if descriptor is not None:
                actions.append(descriptor)
        return actions
