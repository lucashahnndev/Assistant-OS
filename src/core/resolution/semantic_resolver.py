from typing import Optional, Dict, Any, List, Tuple
from .base import IntentResolver
from .action_plan import ActionPlan
import logging
import re

logger = logging.getLogger("SemanticResolver")

class SemanticResolver(IntentResolver):
    def __init__(self, threshold: float = 0.92, skill_registry: Any = None):
        self.threshold = threshold
        self.skill_registry = skill_registry
        self.safe_patterns: List[Tuple[re.Pattern, str, Any]] = [
            # Time / status / info
            (re.compile(r"\b(que horas|hora atual|what time|current time)\b", re.IGNORECASE), "system.control.time", self._no_params),
            (re.compile(r"\b(status do sistema|status system|system status|estado do sistema)\b", re.IGNORECASE), "system.control.status", self._no_params),
            (re.compile(r"\b(info do sistema|system info|informacoes do sistema|informações do sistema)\b", re.IGNORECASE), "system.control.info", self._no_params),
            (re.compile(r"\b(screenshot|print da tela|captura de tela|tirar print)\b", re.IGNORECASE), "system.control.screenshot", self._no_params),
            # Search / knowledge
            (re.compile(r"\b(wikipedia|wikip[eé]dia|wiki)\b", re.IGNORECASE), "wikipedia.search", self._wikipedia_params),
            (re.compile(r"\b(pesquise|pesquisar|procure|buscar|search|look up)\b", re.IGNORECASE), "web.search.discover", self._query_param),
            (re.compile(r"\b(clima|tempo hoje|previs[aã]o do tempo|weather)\b", re.IGNORECASE), "weather.control.get", self._weather_params),
            # Media playback (robust against typos, useful when JSON intent is malformed)
            (
                re.compile(
                    r"\b(reproduz|reproduzir|reporduz|toca|tocar|play|ouvir)\b.*\b(youtube music|ytoutbe music|yt music|youtube)\b|\b(youtube music|ytoutbe music|yt music|youtube)\b.*\b(reproduz|reproduzir|reporduz|toca|tocar|play|ouvir)\b",
                    re.IGNORECASE,
                ),
                "youtube.search.find",
                self._media_query_params,
            ),
            (
                re.compile(
                    r"\b(reproduz|reproduzir|reproduza|reporduz|toca|tocar|play|ouvir)\b.*\b(musica|música|song|faixa|cantor|artista)\b",
                    re.IGNORECASE,
                ),
                "youtube.search.find",
                self._media_query_params,
            ),
            (
                re.compile(
                    r"\b(reproduz|reproduzir|reporduz|toca|tocar|play|ouvir)\b.*\b(deezer)\b|\b(deezer)\b.*\b(reproduz|reproduzir|reporduz|toca|tocar|play|ouvir)\b",
                    re.IGNORECASE,
                ),
                "deezer.search.search",
                self._media_query_params,
            ),
            (re.compile(r"\b(youtube)\b.*\b(busca|buscar|search|procure|encontre)\b|\b(busca|buscar|search|procure|encontre)\b.*\b(youtube)\b", re.IGNORECASE), "youtube.search.find", self._query_param),
            (re.compile(r"\b(mapa|maps|perto de|endere[cç]o|rota)\b", re.IGNORECASE), "maps.search.search", self._query_param),
            # Memory
            (re.compile(r"\b(lembrar|recall|mem[oó]ria|memoria)\b", re.IGNORECASE), "memory.recall", self._query_param),
            (re.compile(r"\b(anota|anotar|memoriza|salve na mem[oó]ria|save to memory)\b", re.IGNORECASE), "memory.store", self._memory_store_params),
        ]

    def resolve(self, user_input: str, context: Dict[str, Any]) -> Optional[ActionPlan]:
        logger.debug(f"SemanticResolver: Processing '{user_input}' (Threshold: {self.threshold})")

        registry = context.get("skill_registry") or self.skill_registry
        if not registry:
            logger.debug("SemanticResolver: no skill_registry available.")
            return None

        available_actions = self._get_available_actions(context, registry)
        if not available_actions:
            logger.debug("SemanticResolver: no available actions in scope.")
            return None

        normalized_input = (user_input or "").strip()
        if not normalized_input:
            return None

        # 1) High-precision regex rules for common safe tasks.
        for pattern, action_id, params_builder in self.safe_patterns:
            if not pattern.search(normalized_input):
                continue
            if action_id not in available_actions:
                continue
            params = params_builder(normalized_input)
            confidence = 0.97
            if confidence < self.threshold:
                continue
            return ActionPlan(
                action_id=action_id,
                args=params,
                confidence=confidence,
                source="semantic",
                response_text=None,
                thought=f"Semantic match ({pattern.pattern}) -> {action_id}",
                metadata={"semantic_rule": pattern.pattern},
            )

        # 2) Fallback lexical match based on action id and contract description.
        best_action = None
        best_score = 0.0
        best_reason = ""
        for action_id in available_actions:
            score, reason = self._lexical_similarity(normalized_input, action_id, registry)
            if score > best_score:
                best_score = score
                best_action = action_id
                best_reason = reason

        if best_action and best_score >= self.threshold:
            return ActionPlan(
                action_id=best_action,
                args={},
                confidence=best_score,
                source="semantic",
                response_text=None,
                thought=f"Lexical semantic match -> {best_action}",
                metadata={"semantic_match_reason": best_reason},
            )

        return None

    def _get_available_actions(self, context: Dict[str, Any], registry: Any) -> List[str]:
        allowed_actions = context.get("allowed_actions")
        if allowed_actions is not None:
            return list(allowed_actions)
        if hasattr(registry, "list_actions"):
            return list(registry.list_actions())
        return []

    def _lexical_similarity(self, user_input: str, action_id: str, registry: Any) -> tuple[float, str]:
        tokens_input = self._tokenize(user_input)
        if not tokens_input:
            return 0.0, "empty_input"

        metadata = registry.get_action_metadata(action_id) if hasattr(registry, "get_action_metadata") else {}
        description = str(metadata.get("description", ""))
        corpus = f"{action_id} {description}".strip()
        tokens_action = self._tokenize(corpus)
        if not tokens_action:
            return 0.0, "empty_action_tokens"

        overlap = len(set(tokens_input) & set(tokens_action))
        overlap_ratio = overlap / max(1, len(set(tokens_input)))

        # Direct namespace/local token presence boosts precision.
        action_suffix = action_id.split(".")[-1]
        exact_boost = 0.25 if action_suffix in user_input.lower() else 0.0
        dotless_boost = 0.20 if action_id.replace(".", " ") in user_input.lower() else 0.0

        score = min(1.0, overlap_ratio + exact_boost + dotless_boost)
        reason = f"overlap={overlap_ratio:.2f}, exact_boost={exact_boost:.2f}, dotless_boost={dotless_boost:.2f}"
        return score, reason

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        raw = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
        # Remove very short noise tokens.
        return [t for t in raw if len(t) > 2]

    @staticmethod
    def _no_params(user_input: str) -> Dict[str, Any]:
        return {}

    @staticmethod
    def _query_param(user_input: str) -> Dict[str, Any]:
        # Keep fallback robust: full user sentence still works for search skills.
        cleaned = user_input.strip()
        return {"query": cleaned}

    @staticmethod
    def _wikipedia_params(user_input: str) -> Dict[str, Any]:
        cleaned = user_input.strip()
        match = re.search(
            r"(?:wikipedia|wikip[eé]dia|wiki)\s*(?:sobre|for|about|:)?\s*(.+)$",
            cleaned,
            re.IGNORECASE,
        )
        query = match.group(1).strip() if match and match.group(1).strip() else cleaned
        return {"query": query}

    @staticmethod
    def _weather_params(user_input: str) -> Dict[str, Any]:
        # Simple "em X" extraction for weather requests.
        m = re.search(r"\bem\s+([a-zA-ZÀ-ÿ0-9\s\-]+)$", user_input.strip(), re.IGNORECASE)
        if m:
            return {"city": m.group(1).strip()}
        return {}

    @staticmethod
    def _memory_store_params(user_input: str) -> Dict[str, Any]:
        text = user_input.strip()
        return {"category": "general", "content": text}

    @staticmethod
    def _media_query_params(user_input: str) -> Dict[str, Any]:
        text = (user_input or "").strip().lower()
        # Strip control verbs and media platform hints; keep likely song/artist terms.
        text = re.sub(r"\b(reproduz|reproduzir|reporduz|toca|tocar|play|ouvir|abre|abrir)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(no|na|do|da|de|em|para|a|o|uma|um)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(youtube music|ytoutbe music|yt music|youtube|deezer|spotify)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(musica|música|music)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" \"'")
        if not text:
            text = user_input.strip()
        return {"query": text}
