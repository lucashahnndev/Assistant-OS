#!/usr/bin/env python3
import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACT_ARTIFACTS_PATH = ROOT / "src" / "utils" / "contract_artifacts.py"
_spec = importlib.util.spec_from_file_location(
    "contract_artifacts_module", CONTRACT_ARTIFACTS_PATH
)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load {CONTRACT_ARTIFACTS_PATH}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
write_contract_violation = _module.write_contract_violation


VIOLATION_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - .*Gemini structured contract violation "
    r"contract=(?P<contract>\S+) attempt=(?P<attempt>\d+)/(?P<max_attempts>\d+) error=(?P<error>.*)$"
)


RAW_RE = re.compile(
    r"^.*Gemini structured raw contract=(?P<contract>\S+) attempt=(?P<attempt>\d+)/(?P<max_attempts>\d+) "
    r"chars=(?P<chars>\d+) preview=(?P<preview>.*)$"
)


def _to_iso_utc(ts: str) -> str:
    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.isoformat()


def backfill(log_path: Path, provider: str, model: str) -> int:
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    raw_by_attempt = {}
    emitted = 0

    for line in lines:
        raw_match = RAW_RE.match(line)
        if raw_match:
            key = (
                raw_match.group("contract"),
                raw_match.group("attempt"),
                raw_match.group("max_attempts"),
            )
            raw_by_attempt[key] = {
                "chars": raw_match.group("chars"),
                "preview": raw_match.group("preview"),
            }
            continue

        violation_match = VIOLATION_RE.match(line)
        if not violation_match:
            continue

        contract_name = violation_match.group("contract")
        attempt = int(violation_match.group("attempt"))
        max_attempts = int(violation_match.group("max_attempts"))
        error_text = violation_match.group("error")
        ts_iso = _to_iso_utc(violation_match.group("ts"))
        key = (contract_name, str(attempt), str(max_attempts))
        raw_meta = raw_by_attempt.get(key, {})
        excerpt = raw_meta.get("preview", "")

        write_contract_violation(
            provider=provider,
            model=model,
            contract_name=contract_name,
            prompt="",
            raw_response=excerpt,
            error_text=error_text,
            attempt=attempt,
            max_attempts=max_attempts,
            extra={
                "source": "assistant.log.backfill",
                "source_chars": raw_meta.get("chars"),
                "source_timestamp": ts_iso,
            },
        )
        emitted += 1

    return emitted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill contract violation artifacts from assistant.log"
    )
    parser.add_argument(
        "--log",
        default="data/logs/assistant.log",
        help="Path to assistant log file",
    )
    parser.add_argument(
        "--provider",
        default="gemini",
        help="Provider label used in artifact file name",
    )
    parser.add_argument(
        "--model",
        default="google-1",
        help="Model/provider id for artifact metadata",
    )
    args = parser.parse_args()

    count = backfill(Path(args.log), provider=args.provider, model=args.model)
    print(json.dumps({"emitted": count, "log": args.log, "provider": args.provider}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
