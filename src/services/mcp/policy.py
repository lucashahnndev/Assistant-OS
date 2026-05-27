from __future__ import annotations

from .models import MCPPolicyDecision, MCPServerConfig, MCPToolDescriptor


class MCPPolicyGate:
    def evaluate_tool(self, server: MCPServerConfig, tool: MCPToolDescriptor) -> MCPPolicyDecision:
        if not server.enabled:
            return MCPPolicyDecision(
                allowed=False,
                reason="server_disabled",
                risk_level="high",
                requires_approval=True,
                read_only=False,
                destructive=False,
            )

        tool_name = str(tool.name or "").strip()
        if tool_name in set(server.policy.tool_denylist or []):
            return MCPPolicyDecision(
                allowed=False,
                reason="tool_denied",
                risk_level="high",
                requires_approval=True,
                read_only=False,
                destructive=False,
            )
        allowlist = list(server.policy.tool_allowlist or [])
        if allowlist and tool_name not in set(allowlist):
            return MCPPolicyDecision(
                allowed=False,
                reason="tool_not_allowlisted",
                risk_level="high",
                requires_approval=True,
                read_only=False,
                destructive=False,
            )

        read_only = bool(tool.annotations.readOnlyHint)
        destructive = bool(tool.annotations.destructiveHint)

        risk_level = "low" if read_only else "medium"
        if destructive:
            risk_level = "high"
        elif server.policy.trust_tier == "untrusted":
            risk_level = "high" if not read_only else "medium"
        elif server.policy.trust_tier == "partner" and not read_only:
            risk_level = "medium"

        if server.policy.default_requires_approval is not None:
            requires_approval = bool(server.policy.default_requires_approval)
        else:
            requires_approval = destructive or not read_only or server.policy.trust_tier == "untrusted"

        return MCPPolicyDecision(
            allowed=True,
            reason="allowed",
            risk_level=risk_level,
            requires_approval=bool(requires_approval),
            read_only=read_only,
            destructive=destructive,
        )
