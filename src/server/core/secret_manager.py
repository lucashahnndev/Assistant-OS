from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from cryptography.fernet import Fernet, InvalidToken


SENSITIVE_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS", "PRIVATE", "JWT", "AUTH", "ID")
INTERNAL_ENV_EXACT = {
    "SECRET_MANAGEMENT_KEY",
    "PORTAL_SECRET_KEY",
}
INTERNAL_ENV_PREFIXES = (
    "SECRET_TRANSPORT_",
    "SECRET_VAULT_",
)
VAULT_VERSION = 1
ENV_VAULT_KEY = "SECRET_VAULT_MASTER_KEY"
ENV_VAULT_KEY_FILE = "SECRET_VAULT_MASTER_KEY_FILE"


class SecretVaultError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _data_dir() -> str:
    env_dir = os.environ.get("AOSD_DATA_DIR")
    if env_dir:
        return env_dir
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    local_data = os.path.join(project_root, "data")
    if os.path.exists(local_data):
        return local_data
    return os.path.expanduser("~/aosd")


def _vault_dir() -> str:
    path = os.path.join(_data_dir(), "secrets")
    os.makedirs(path, exist_ok=True)
    return path


def _vault_path() -> str:
    return os.path.join(_vault_dir(), "secrets.json.enc")


def _default_vault_key_file() -> str:
    return os.path.join(_vault_dir(), "secret_vault.key")


def _write_text_atomic(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".vault.", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _read_key_file(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return str(handle.read() or "").strip()


def _ensure_vault_master_key() -> str:
    raw_key = str(os.getenv(ENV_VAULT_KEY, "") or "").strip()
    if raw_key:
        return raw_key

    key_file = str(os.getenv(ENV_VAULT_KEY_FILE, "") or "").strip() or _default_vault_key_file()
    raw_key = _read_key_file(key_file)
    if raw_key:
        return raw_key

    generated = Fernet.generate_key().decode("utf-8")
    _write_text_atomic(key_file, f"{generated}\n")
    try:
        os.chmod(key_file, 0o600)
    except Exception:
        pass
    return generated


def _get_fernet() -> Fernet:
    raw_key = _ensure_vault_master_key()
    try:
        return Fernet(raw_key.encode("utf-8"))
    except Exception as exc:
        raise SecretVaultError(f"Invalid vault master key: {exc}") from exc


def read_env_file(path: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path or not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def to_config_ref(key: str) -> str:
    token = str(key or "").strip()
    if not token:
        return ""
    return token if token.startswith("ENV_") else f"ENV_{token}"


def to_env_key(key: str) -> str:
    token = str(key or "").strip()
    if token.startswith("ENV_"):
        token = token[4:]
    return token


def _is_secret_like_key(key: str) -> bool:
    token = str(key or "").strip().upper()
    if not token:
        return False
    if token in INTERNAL_ENV_EXACT:
        return False
    if any(token.startswith(prefix) for prefix in INTERNAL_ENV_PREFIXES):
        return False
    if token.startswith("ENV_"):
        return True
    return any(token.endswith(suffix) for suffix in SENSITIVE_ENV_HINTS)


def _empty_payload() -> Dict[str, Any]:
    return {"version": VAULT_VERSION, "secrets": {}}


def _load_vault_payload() -> Dict[str, Any]:
    path = _vault_path()
    if not os.path.exists(path):
        return _empty_payload()
    try:
        with open(path, "rb") as handle:
            encrypted = handle.read()
        if not encrypted:
            return _empty_payload()
        raw = _get_fernet().decrypt(encrypted)
        payload = json.loads(raw.decode("utf-8"))
    except InvalidToken as exc:
        raise SecretVaultError("Unable to decrypt secrets vault") from exc
    except Exception as exc:
        raise SecretVaultError(f"Unable to read secrets vault: {exc}") from exc

    if not isinstance(payload, dict):
        raise SecretVaultError("Invalid secrets vault payload")
    payload.setdefault("version", VAULT_VERSION)
    payload.setdefault("secrets", {})
    if not isinstance(payload.get("secrets"), dict):
        raise SecretVaultError("Invalid secrets vault content")
    return payload


def _write_vault_payload(payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    encrypted = _get_fernet().encrypt(data)
    directory = _vault_dir()
    fd, tmp_path = tempfile.mkstemp(prefix="secrets.", suffix=".enc.tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encrypted)
        os.replace(tmp_path, _vault_path())
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def encrypt_sensitive_json(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _get_fernet().encrypt(raw).decode("utf-8")


def decrypt_sensitive_json(token: str) -> Dict[str, Any]:
    try:
        raw = _get_fernet().decrypt(str(token or "").encode("utf-8"))
        payload = json.loads(raw.decode("utf-8"))
    except InvalidToken as exc:
        raise SecretVaultError("Unable to decrypt sensitive payload") from exc
    except Exception as exc:
        raise SecretVaultError(f"Unable to decode sensitive payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise SecretVaultError("Sensitive payload must decode to an object")
    return payload


def _get_secret_record(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    config_ref = to_config_ref(key)
    record = payload.get("secrets", {}).get(config_ref)
    if isinstance(record, dict):
        return record
    return {}


def resolve_secret_ref(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if token.startswith("ENV_"):
        payload = _load_vault_payload()
        record = _get_secret_record(payload, token)
        vault_value = str(record.get("value") or "").strip()
        if vault_value:
            return vault_value
        return ""
    return token


def list_secret_refs(_path: str = None) -> List[str]:
    payload = _load_vault_payload()
    refs = [key for key in payload.get("secrets", {}).keys() if to_config_ref(key)]
    return sorted(set(refs))


def list_secret_entries() -> List[Dict[str, Any]]:
    payload = _load_vault_payload()
    entries: List[Dict[str, Any]] = []
    for key, record in sorted(payload.get("secrets", {}).items()):
        if not isinstance(record, dict):
            continue
        value = str(record.get("value") or "")
        entries.append(
            {
                "key": to_config_ref(key),
                "has_value": bool(value),
                "created_at": record.get("created_at") or None,
                "updated_at": record.get("updated_at") or None,
                "source": "vault",
            }
        )
    return entries


def upsert_secret(_path: str = None, *, key: str, value: str, overwrite: bool = False) -> Dict[str, str]:
    config_ref = to_config_ref(key)
    env_key = to_env_key(key)
    if not env_key:
        raise ValueError("Invalid key")

    payload = _load_vault_payload()
    secrets = payload.setdefault("secrets", {})
    existing = secrets.get(config_ref)
    if existing and not overwrite:
        raise FileExistsError("Key already exists in vault")

    now = _utc_now()
    created_at = now
    if isinstance(existing, dict) and existing.get("created_at"):
        created_at = str(existing.get("created_at"))

    secrets[config_ref] = {
        "value": str(value),
        "env_key": env_key,
        "created_at": created_at,
        "updated_at": now,
    }
    _write_vault_payload(payload)
    return {"config_ref": config_ref, "env_key": env_key}


def delete_secret(_path: str = None, *, key: str) -> Dict[str, str]:
    config_ref = to_config_ref(key)
    env_key = to_env_key(key)
    if not env_key:
        raise ValueError("Invalid key")

    payload = _load_vault_payload()
    secrets = payload.setdefault("secrets", {})
    if config_ref not in secrets:
        raise KeyError("Secret key not found")
    secrets.pop(config_ref, None)
    _write_vault_payload(payload)
    return {"env_key": env_key, "config_ref": config_ref}


def audit_env_file(path: str) -> Dict[str, Any]:
    env_data = read_env_file(path)
    payload = _load_vault_payload()
    vault = payload.get("secrets", {})

    missing: List[str] = []
    divergent: List[str] = []
    matched: List[str] = []
    ignored: List[str] = []

    for raw_key, env_value in sorted(env_data.items()):
        if not _is_secret_like_key(raw_key):
            ignored.append(raw_key)
            continue
        config_ref = to_config_ref(raw_key)
        record = vault.get(config_ref)
        if not isinstance(record, dict):
            missing.append(config_ref)
            continue
        vault_value = str(record.get("value") or "")
        if vault_value == str(env_value):
            matched.append(config_ref)
        else:
            divergent.append(config_ref)

    return {
        "env_path": path,
        "vault_path": _vault_path(),
        "missing": missing,
        "divergent": divergent,
        "matched": matched,
        "ignored": ignored,
        "summary": {
            "missing": len(missing),
            "divergent": len(divergent),
            "matched": len(matched),
            "ignored": len(ignored),
        },
    }


def import_env_file(path: str, *, overwrite: bool = False) -> Dict[str, Any]:
    env_data = read_env_file(path)
    imported: List[str] = []
    updated: List[str] = []
    skipped: List[str] = []
    ignored: List[str] = []

    payload = _load_vault_payload()
    secrets = payload.setdefault("secrets", {})
    now = _utc_now()

    for raw_key, env_value in sorted(env_data.items()):
        if not _is_secret_like_key(raw_key):
            ignored.append(raw_key)
            continue
        config_ref = to_config_ref(raw_key)
        existing = secrets.get(config_ref)
        if isinstance(existing, dict):
            current_value = str(existing.get("value") or "")
            if current_value == str(env_value):
                skipped.append(config_ref)
                continue
            if not overwrite:
                skipped.append(config_ref)
                continue
            secrets[config_ref] = {
                **existing,
                "value": str(env_value),
                "env_key": to_env_key(raw_key),
                "updated_at": now,
                "created_at": existing.get("created_at") or now,
            }
            updated.append(config_ref)
            continue

        secrets[config_ref] = {
            "value": str(env_value),
            "env_key": to_env_key(raw_key),
            "created_at": now,
            "updated_at": now,
        }
        imported.append(config_ref)

    _write_vault_payload(payload)
    return {
        "env_path": path,
        "vault_path": _vault_path(),
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "ignored": ignored,
        "summary": {
            "imported": len(imported),
            "updated": len(updated),
            "skipped": len(skipped),
            "ignored": len(ignored),
        },
    }


def vault_metadata() -> Dict[str, str]:
    return {
        "vault_path": _vault_path(),
        "key_file": str(os.getenv(ENV_VAULT_KEY_FILE, "") or _default_vault_key_file()),
    }
