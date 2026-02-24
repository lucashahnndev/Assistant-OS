from __future__ import annotations

import json
import os
from typing import Any, Dict


class I18nService:
    """Simple translation package loader with fallback to English."""

    def __init__(self, locales_dir: str | None = None, default_locale: str = "en"):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.locales_dir = locales_dir or os.path.join(root, "locales")
        self.default_locale = default_locale
        self._cache: Dict[str, Dict[str, str]] = {}

    def t(self, key: str, locale: str | None = None, **kwargs: Any) -> str:
        target = (locale or self.default_locale or "en").strip()
        catalog = self._load_catalog(target)
        default_catalog = self._load_catalog(self.default_locale)
        template = catalog.get(key) or default_catalog.get(key) or key
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def _load_catalog(self, locale: str) -> Dict[str, str]:
        normalized = self._normalize_locale(locale)
        if normalized in self._cache:
            return self._cache[normalized]

        path = os.path.join(self.locales_dir, f"{normalized}.json")
        data: Dict[str, str] = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
                if isinstance(loaded, dict):
                    data = {str(k): str(v) for k, v in loaded.items()}

        self._cache[normalized] = data
        return data

    @staticmethod
    def _normalize_locale(locale: str) -> str:
        value = (locale or "en").strip().replace("_", "-")
        if not value:
            return "en"
        lowered = value.lower()
        if lowered.startswith("pt"):
            return "pt-BR"
        if lowered.startswith("en"):
            return "en"
        return value
