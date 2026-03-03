from __future__ import annotations

import json
import os
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken


class TokenVaultError(RuntimeError):
    pass


class TokenVault:
    """Encrypts/decrypts sensitive OAuth tokens for persistence."""

    ENV_KEY = "EXTERNAL_ACCOUNTS_ENCRYPTION_KEY"

    def __init__(self) -> None:
        raw_key = os.getenv(self.ENV_KEY, "").strip()
        if not raw_key:
            raise TokenVaultError(
                f"Missing {self.ENV_KEY}. Generate one with: "
                "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        try:
            self._fernet = Fernet(raw_key.encode("utf-8"))
        except Exception as exc:
            raise TokenVaultError(f"Invalid {self.ENV_KEY}: {exc}") from exc

    def encrypt_json(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._fernet.encrypt(raw).decode("utf-8")

    def decrypt_json(self, token: str) -> Dict[str, Any]:
        try:
            raw = self._fernet.decrypt(str(token or "").encode("utf-8"))
            return json.loads(raw.decode("utf-8"))
        except InvalidToken as exc:
            raise TokenVaultError("Unable to decrypt token payload") from exc


def get_token_vault() -> TokenVault:
    return TokenVault()
