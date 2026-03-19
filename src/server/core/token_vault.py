from __future__ import annotations

from typing import Any, Dict

from .secret_manager import decrypt_sensitive_json, encrypt_sensitive_json, SecretVaultError


class TokenVaultError(RuntimeError):
    pass


class TokenVault:
    """Encrypts/decrypts OAuth token payloads using the unified secrets vault crypto backend."""

    def encrypt_json(self, payload: Dict[str, Any]) -> str:
        try:
            return encrypt_sensitive_json(payload)
        except SecretVaultError as exc:
            raise TokenVaultError(str(exc)) from exc

    def decrypt_json(self, token: str) -> Dict[str, Any]:
        try:
            return decrypt_sensitive_json(token)
        except SecretVaultError as exc:
            raise TokenVaultError(str(exc)) from exc


def get_token_vault() -> TokenVault:
    return TokenVault()
