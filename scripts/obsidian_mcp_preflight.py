#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.services.mcp.client import MCPClientManager
from src.services.mcp.models import MCPServerConfig
from src.services.mcp.registry import MCPServerRegistry


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _extract_mcp_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    mcp = cfg.get("mcp") if isinstance(cfg.get("mcp"), dict) else {}
    return dict(mcp)


def _obsidian_config_candidates() -> List[Path]:
    return [
        Path.home() / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian" / "obsidian.json",
        Path.home() / ".config" / "obsidian" / "obsidian.json",
    ]


def discover_obsidian_vaults() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for candidate in _obsidian_config_candidates():
        if not candidate.exists():
            continue
        try:
            payload = _load_json(str(candidate))
        except Exception:
            continue
        vaults = payload.get("vaults") if isinstance(payload.get("vaults"), dict) else {}
        for vault_id, item in vaults.items():
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "vault_id": str(vault_id),
                    "path": str(item.get("path") or ""),
                    "open": bool(item.get("open")),
                    "ts": item.get("ts"),
                    "source": str(candidate),
                }
            )
    rows.sort(key=lambda row: (not bool(row.get("open")), str(row.get("path") or "")))
    return rows


def analyze_obsidian_mcp_readiness(mcp_cfg: Dict[str, Any], *, server_id: str = "obsidian") -> Dict[str, Any]:
    cfg = mcp_cfg if isinstance(mcp_cfg, dict) else {}
    issues: List[str] = []
    warnings: List[str] = []

    if not bool(cfg.get("enabled", False)):
        issues.append("mcp_disabled")

    registry = MCPServerRegistry()
    try:
        registry.load_from_config(cfg)
    except Exception as exc:
        return {
            "ready": False,
            "issues": ["mcp_config_invalid"],
            "warnings": [],
            "error_details": str(exc),
            "server_id": server_id,
        }

    server = registry.get(server_id)
    if server is None:
        issues.append("obsidian_server_missing")
        return {"ready": False, "issues": issues, "warnings": warnings, "server_id": server_id}

    if not bool(server.enabled):
        issues.append("obsidian_server_disabled")

    transport_kind = str(server.transport.kind or "").strip().lower()
    if transport_kind == "http":
        if not str(server.transport.endpoint or "").strip():
            issues.append("obsidian_endpoint_missing")
    elif transport_kind == "stdio":
        if not str(server.transport.command or "").strip():
            issues.append("obsidian_stdio_command_missing")
    else:
        issues.append("obsidian_transport_unsupported")

    if not bool(server.policy.allow_tool_discovery):
        warnings.append("tool_discovery_disabled")
    if not bool(server.policy.allow_resources):
        warnings.append("resources_disabled")

    return {
        "ready": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "server_id": server_id,
        "transport_kind": transport_kind,
        "endpoint": str(server.transport.endpoint or ""),
        "command": str(server.transport.command or ""),
    }


def cmd_discover_vaults(_args: argparse.Namespace) -> Dict[str, Any]:
    rows = discover_obsidian_vaults()
    return {
        "ok": True,
        "mode": "discover-vaults",
        "count": len(rows),
        "vaults": rows,
    }


def cmd_check_config(args: argparse.Namespace) -> Dict[str, Any]:
    path = str(args.config_file or "").strip()
    if not path:
        return {"ok": False, "error_code": "MISSING_CONFIG_PATH"}
    if not os.path.exists(path):
        return {"ok": False, "error_code": "CONFIG_NOT_FOUND", "config_file": path}

    cfg = _load_json(path)
    mcp_cfg = _extract_mcp_cfg(cfg)
    readiness = analyze_obsidian_mcp_readiness(mcp_cfg, server_id=str(args.server_id or "obsidian"))
    payload = {
        "ok": True,
        "mode": "check-config",
        "config_file": path,
        "obsidian_mcp": readiness,
        "vaults": discover_obsidian_vaults(),
    }
    if bool(getattr(args, "require_ready", False)) and not readiness.get("ready"):
        payload["ok"] = False
        payload["error_code"] = "OBSIDIAN_MCP_NOT_READY"
    return payload


def cmd_probe_server(args: argparse.Namespace) -> Dict[str, Any]:
    server_id = str(args.server_id or "obsidian").strip().lower()
    cfg = {}
    if str(args.config_file or "").strip():
        path = str(args.config_file or "").strip()
        if not os.path.exists(path):
            return {"ok": False, "error_code": "CONFIG_NOT_FOUND", "config_file": path}
        cfg = _extract_mcp_cfg(_load_json(path))
    else:
        return {"ok": False, "error_code": "MISSING_CONFIG_PATH"}

    registry = MCPServerRegistry()
    registry.load_from_config(cfg)
    server = registry.get(server_id)
    if server is None:
        return {"ok": False, "error_code": "OBSIDIAN_SERVER_NOT_FOUND", "server_id": server_id}

    manager = MCPClientManager()
    t0 = time.time()
    try:
        tools = manager.list_tools(server) if bool(server.policy.allow_tool_discovery) else []
        resources = manager.list_resources(server) if bool(server.policy.allow_resources) else []
    except Exception as exc:
        return {
            "ok": False,
            "mode": "probe-server",
            "server_id": server_id,
            "error_code": "OBSIDIAN_MCP_PROBE_FAILED",
            "error_details": str(exc),
        }
    finally:
        manager.close_all()

    return {
        "ok": True,
        "mode": "probe-server",
        "server_id": server_id,
        "latency_ms": int((time.time() - t0) * 1000),
        "tool_count": len(tools),
        "resource_count": len(resources),
        "tools": [tool.name for tool in tools[:20]],
        "resources": [resource.uri for resource in resources[:20]],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Obsidian MCP preflight utility")
    parser.add_argument(
        "--config-file",
        default=os.path.join(str(ROOT), "data", "config.json"),
        help="Path to config.json used by Atlas",
    )
    parser.add_argument("--server-id", default="obsidian", help="MCP server id to inspect")

    sub = parser.add_subparsers(dest="command", required=True)

    p_discover = sub.add_parser("discover-vaults", help="Discover local Obsidian vaults")
    p_discover.set_defaults(handler=cmd_discover_vaults)

    p_check = sub.add_parser("check-config", help="Validate Obsidian MCP config readiness")
    p_check.add_argument("--require-ready", action="store_true")
    p_check.set_defaults(handler=cmd_check_config)

    p_probe = sub.add_parser("probe-server", help="Probe Obsidian MCP server via configured transport")
    p_probe.set_defaults(handler=cmd_probe_server)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = args.handler(args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
