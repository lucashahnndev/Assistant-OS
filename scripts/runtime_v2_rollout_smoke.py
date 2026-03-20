#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.services.agent_runtime_v2 import PolicyRolloutEngine


class _Cfg:
    def __init__(self, base_data_dir: str):
        self.base_data_dir = base_data_dir

    def get(self, key: str, default=None):
        return default


def _build_engine(base_data_dir: str) -> PolicyRolloutEngine:
    return PolicyRolloutEngine(config_manager=_Cfg(base_data_dir))


def cmd_check(args: argparse.Namespace) -> Dict[str, Any]:
    engine = _build_engine(args.base_data_dir)
    policy = engine.get_policy(args.policy_id)
    if not policy:
        return {
            "ok": False,
            "error_code": "POLICY_NOT_FOUND",
            "policy_id": args.policy_id,
        }
    return {
        "ok": True,
        "mode": "check",
        "policy_id": args.policy_id,
        "state": str(policy.get("state", "")),
        "canary": dict(policy.get("canary", {}) or {}),
    }


def cmd_canary_check(args: argparse.Namespace) -> Dict[str, Any]:
    engine = _build_engine(args.base_data_dir)
    out = engine.evaluate_canary_regression(
        policy_id=args.policy_id,
        metrics={
            "error_rate": float(args.error_rate),
            "latency_increase": float(args.latency_increase),
        },
        thresholds={
            "max_error_rate": float(args.max_error_rate),
            "max_latency_increase": float(args.max_latency_increase),
        },
    )
    out["mode"] = "canary_check"
    out["policy_id"] = args.policy_id
    return out


def cmd_rollback_check(args: argparse.Namespace) -> Dict[str, Any]:
    engine = _build_engine(args.base_data_dir)
    rollback = engine.rollback(policy_id=args.policy_id, reason=args.reason)
    if not rollback.get("ok"):
        rollback["mode"] = "rollback_check"
        rollback["policy_id"] = args.policy_id
        return rollback
    policy = engine.get_policy(args.policy_id)
    return {
        "ok": True,
        "mode": "rollback_check",
        "policy_id": args.policy_id,
        "state": str(policy.get("state", "")),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Runtime v2 policy rollout smoke helper")
    parser.add_argument(
        "--base-data-dir",
        default=os.path.join(str(ROOT), "data"),
        help="Base data directory containing runtime_v2 state files",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Check policy presence/state")
    p_check.add_argument("--policy-id", required=True)
    p_check.set_defaults(handler=cmd_check)

    p_canary = sub.add_parser("canary-check", help="Evaluate canary regression thresholds")
    p_canary.add_argument("--policy-id", required=True)
    p_canary.add_argument("--error-rate", type=float, required=True)
    p_canary.add_argument("--latency-increase", type=float, required=True)
    p_canary.add_argument("--max-error-rate", type=float, default=0.2)
    p_canary.add_argument("--max-latency-increase", type=float, default=0.5)
    p_canary.set_defaults(handler=cmd_canary_check)

    p_rb = sub.add_parser("rollback-check", help="Force rollback and confirm rolled_back state")
    p_rb.add_argument("--policy-id", required=True)
    p_rb.add_argument("--reason", default="manual_rollback_check")
    p_rb.set_defaults(handler=cmd_rollback_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out = args.handler(args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
