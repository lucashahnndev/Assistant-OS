from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse


@dataclass
class PolicyDecision:
    route: str
    reason: str
    use_app_mode: bool
    force_new_instance: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route,
            "reason": self.reason,
            "use_app_mode": self.use_app_mode,
            "force_new_instance": self.force_new_instance,
        }


class BrowserSessionPolicy:
    """
    Deterministic routing policy for browser sessions.
    This keeps CDP/session decisions out of LLM responsibilities.
    """

    _MEDIA_INTENT = "controlar_midia"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.app_mode_enabled = bool(cfg.get("app_mode_enabled", True))
        # In production chat flows, session identifiers may rotate/reconnect while the
        # same user/browser task is still active. Enforcing hard instance recreation on
        # session switch causes open/close thrashing and token-wasting loops.
        # Keep strict isolation as an opt-in.
        self.strict_session_isolation = bool(cfg.get("strict_session_isolation", False))

    @staticmethod
    def _domain(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if "://" not in raw:
            raw = f"https://{raw}"
        try:
            return str(urlparse(raw).netloc or "").lower()
        except Exception:
            return ""

    def decide(
        self,
        *,
        intent_class: str,
        goal: str,
        owner_session_id: str,
        current_owner_session_id: Optional[str],
        current_intent_class: Optional[str],
        has_runtime: bool,
        launch_url: str = "",
        current_url: str = "",
    ) -> PolicyDecision:
        _ = goal  # goal reserved for future URL/domain classifiers
        media_intent = str(intent_class or "").strip().lower() == self._MEDIA_INTENT
        use_app_mode = self.app_mode_enabled and media_intent

        if not has_runtime:
            return PolicyDecision(
                route="new_instance",
                reason="cold_start",
                use_app_mode=use_app_mode,
                force_new_instance=True,
            )

        if current_owner_session_id and str(current_owner_session_id) != str(owner_session_id):
            return PolicyDecision(
                route="reuse_tab",
                reason="session_switch_reuse_without_close",
                use_app_mode=use_app_mode,
                force_new_instance=False,
            )

        if media_intent and str(current_intent_class or "").strip().lower() != self._MEDIA_INTENT:
            return PolicyDecision(
                route="reuse_tab",
                reason="media_mode_reuse_without_close",
                use_app_mode=use_app_mode,
                force_new_instance=False,
            )

        requested_domain = self._domain(launch_url)
        current_domain = self._domain(current_url)
        if (
            not media_intent
            and requested_domain
            and current_domain
            and requested_domain != current_domain
        ):
            return PolicyDecision(
                route="new_tab",
                reason="cross_domain_navigation",
                use_app_mode=use_app_mode,
                force_new_instance=False,
            )

        return PolicyDecision(
            route="reuse_tab",
            reason="same_session_reuse",
            use_app_mode=use_app_mode,
            force_new_instance=False,
        )
