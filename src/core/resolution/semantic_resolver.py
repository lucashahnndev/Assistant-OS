from typing import Optional, Dict, Any, List, Tuple
from .base import IntentResolver
from .action_plan import ActionPlan
from services.search.query_semantics import QuerySemantics
import logging
import re

logger = logging.getLogger("SemanticResolver")


class SemanticResolver(IntentResolver):
    def __init__(self, threshold: float = 0.92, skill_registry: Any = None):
        self.threshold = threshold
        self.skill_registry = skill_registry
        # English-first semantics with Portuguese aliases for multilingual compatibility.
        self.safe_patterns: List[Tuple[re.Pattern, str, Any]] = [
            (
                re.compile(r"^\s*(oi|ol[aá]|ola|hello|hi|hey)\s*[!.?]*\s*$", re.IGNORECASE),
                "reply",
                self._greeting_reply_params,
            ),
            (re.compile(r"\b(what time|current time|que horas|hora atual)\b", re.IGNORECASE), "system.control.time", self._no_params),
            (re.compile(r"\b(system status|status do sistema|estado do sistema)\b", re.IGNORECASE), "system.control.status", self._no_params),
            (re.compile(r"\b(system info|info do sistema|informacoes do sistema|informações do sistema)\b", re.IGNORECASE), "system.control.info", self._no_params),
            (re.compile(r"\b(screenshot|screen capture|print da tela|captura de tela|tirar print)\b", re.IGNORECASE), "system.control.screenshot", self._no_params),
            (
                re.compile(
                    r"\b(create task|new task|criar tarefa|crie uma tarefa|nova tarefa|agendar tarefa|agende uma tarefa)\b",
                    re.IGNORECASE,
                ),
                "task.scheduler.create",
                self._task_create_params,
            ),
            (re.compile(r"\b(wikipedia|wikip[eé]dia|wiki)\b", re.IGNORECASE), "wikipedia.search", self._wikipedia_params),
            (re.compile(r"\b(search|look up|find|pesquise|pesquisar|procure|buscar)\b", re.IGNORECASE), "web.search.discover", self._query_param),
            (
                re.compile(
                    r"\b(chov\w*|rain\w*)\b.*\b(tomorrow|amanh\w*)\b|\b(tomorrow|amanh\w*)\b.*\b(chov\w*|rain\w*)\b|\b(previs[aã]o|forecast)\b.*\b(tomorrow|amanh\w*)\b",
                    re.IGNORECASE,
                ),
                "weather.control.forecast",
                self._weather_forecast_params,
            ),
            (re.compile(r"\b(weather|forecast|clima|tempo hoje|previs[aã]o do tempo)\b", re.IGNORECASE), "weather.control.get", self._weather_params),
            (
                re.compile(
                    r"\b(play|listen|reproduz|reproduzir|reporduz|toca|tocar|ouvir)\b.*\b(youtube music|yt music|youtube|ytoutbe music)\b|\b(youtube music|yt music|youtube|ytoutbe music)\b.*\b(play|listen|reproduz|reproduzir|reporduz|toca|tocar|ouvir)\b",
                    re.IGNORECASE,
                ),
                "youtube.search.find",
                self._media_query_params,
            ),
            (
                re.compile(
                    r"\b(play|listen|reproduz|reproduzir|reproduza|reporduz|toca|tocar|ouvir)\b.*\b(song|track|artist|musica|música|faixa|cantor|artista)\b",
                    re.IGNORECASE,
                ),
                "youtube.search.find",
                self._media_query_params,
            ),
            (
                re.compile(
                    r"\b(play|listen|reproduz|reproduzir|reporduz|toca|tocar|ouvir)\b.*\b(deezer)\b|\b(deezer)\b.*\b(play|listen|reproduz|reproduzir|reporduz|toca|tocar|ouvir)\b",
                    re.IGNORECASE,
                ),
                "deezer.search.search",
                self._media_query_params,
            ),
            (re.compile(r"\b(youtube)\b.*\b(search|find|busca|buscar|procure|encontre)\b|\b(search|find|busca|buscar|procure|encontre)\b.*\b(youtube)\b", re.IGNORECASE), "youtube.search.find", self._query_param),
            (re.compile(r"\b(map|maps|near|address|route|mapa|perto de|endere[cç]o|rota)\b", re.IGNORECASE), "maps.search.search", self._maps_params),
            (re.compile(r"\b(remember|recall|lembrar|mem[oó]ria|memoria)\b", re.IGNORECASE), "memory.recall", self._query_param),
            (re.compile(r"\b(note|save to memory|anota|anotar|memoriza|salve na mem[oó]ria)\b", re.IGNORECASE), "memory.store", self._memory_store_params),
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

        retry_plan = self._resolve_retry_request(normalized_input, context, available_actions)
        if retry_plan:
            return retry_plan

        for pattern, action_id, params_builder in self.safe_patterns:
            if not pattern.search(normalized_input):
                continue
            # Internal reply/error actions are orchestrator-native and do not depend on skill scope.
            if action_id not in {"reply", "error"} and action_id not in available_actions:
                continue
            params = params_builder(normalized_input)
            response_text = None
            if action_id == "reply" and isinstance(params, dict):
                response_text = params.get("response_text")
            confidence = 0.97
            if confidence < self.threshold:
                continue
            return ActionPlan(
                action_id=action_id,
                args=params,
                confidence=confidence,
                source="semantic",
                response_text=response_text,
                thought=f"Semantic match ({pattern.pattern}) -> {action_id}",
                metadata={"semantic_rule": pattern.pattern},
            )

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

    def _resolve_retry_request(
        self,
        user_input: str,
        context: Dict[str, Any],
        available_actions: List[str],
    ) -> Optional[ActionPlan]:
        if not self._looks_like_retry_request(user_input):
            return None

        session = context.get("session")
        if not session:
            return None
        session_ctx = session.context if isinstance(getattr(session, "context", None), dict) else {}
        last_plan = session_ctx.get("last_action_plan")
        if not isinstance(last_plan, dict):
            return None

        action_id = str(last_plan.get("action_id") or "").strip()
        if not action_id or action_id in {"reply", "error"}:
            return None
        if action_id not in available_actions:
            return None

        args = last_plan.get("args")
        if not isinstance(args, dict):
            args = {}

        return ActionPlan(
            action_id=action_id,
            args=args,
            confidence=0.98,
            source="semantic",
            response_text=None,
            thought=f"Retry request resolved to last action '{action_id}'.",
            metadata={"semantic_rule": "retry_last_action"},
        )

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

        action_suffix = action_id.split(".")[-1]
        exact_boost = 0.25 if action_suffix in user_input.lower() else 0.0
        dotless_boost = 0.20 if action_id.replace(".", " ") in user_input.lower() else 0.0

        score = min(1.0, overlap_ratio + exact_boost + dotless_boost)
        reason = f"overlap={overlap_ratio:.2f}, exact_boost={exact_boost:.2f}, dotless_boost={dotless_boost:.2f}"
        return score, reason

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        raw = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
        return [t for t in raw if len(t) > 2]

    @staticmethod
    def _looks_like_retry_request(user_input: str) -> bool:
        text = (user_input or "").strip().lower()
        if not text:
            return False
        patterns = (
            r"\b(rode|roda|rodar|executa|execute|tenta|tente)\b.*\b(novamente|de novo)\b",
            r"\b(again|retry|try again|rerun|run again)\b",
            r"\b(continue|continuar)\b",
        )
        return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)

    @staticmethod
    def _no_params(user_input: str) -> Dict[str, Any]:
        return {}

    @staticmethod
    def _query_param(user_input: str) -> Dict[str, Any]:
        cleaned = QuerySemantics.rewrite_for_web(user_input)
        return {"query": cleaned}

    @staticmethod
    def _greeting_reply_params(user_input: str) -> Dict[str, Any]:
        text = (user_input or "").strip().lower()
        is_pt = any(token in text for token in ("oi", "olá", "ola"))
        if is_pt:
            return {"response_text": "Olá! Como posso te ajudar?"}
        return {"response_text": "Hi! How can I help you?"}

    @staticmethod
    def _wikipedia_params(user_input: str) -> Dict[str, Any]:
        cleaned = QuerySemantics.sanitize(user_input)
        before_wiki = re.search(
            r"(?:sobre|about)\s+(.+?)\s+(?:na|no|in|on)?\s*(?:wikipedia|wikip[eé]dia|wiki)\b",
            cleaned,
            re.IGNORECASE,
        )
        after_wiki = re.search(
            r"(?:wikipedia|wikip[eé]dia|wiki)\s*(?:about|sobre|for|:)?\s*(.+)$",
            cleaned,
            re.IGNORECASE,
        )
        if before_wiki and before_wiki.group(1).strip():
            candidate = before_wiki.group(1).strip()
        elif after_wiki and after_wiki.group(1).strip():
            candidate = after_wiki.group(1).strip()
        else:
            candidate = cleaned

        query = QuerySemantics.rewrite_for_wikipedia(candidate)
        if SemanticResolver._looks_like_instruction_only_query(query):
            fallback = QuerySemantics.rewrite_for_wikipedia(cleaned)
            if fallback and not SemanticResolver._looks_like_instruction_only_query(fallback):
                query = fallback

        if not query:
            query = cleaned
        return {"query": query}

    @staticmethod
    def _looks_like_instruction_only_query(query: str) -> bool:
        q = QuerySemantics.sanitize(query).lower()
        if not q:
            return True
        if len(q) <= 3:
            return True
        if re.match(
            r"^(?:e\s+)?(?:forne[cç]a|fornecer|fa[cç]a|resuma|sumarize|summarize|traga|d[eê])\b",
            q,
            re.IGNORECASE,
        ):
            return True
        if any(token in q for token in ("resumo", "summary", "explicação", "explanation")) and len(q.split()) <= 4:
            return True
        return False

    @staticmethod
    def _maps_params(user_input: str) -> Dict[str, Any]:
        cleaned = QuerySemantics.rewrite_for_maps(user_input)
        return {"query": cleaned}

    @staticmethod
    def _weather_params(user_input: str) -> Dict[str, Any]:
        base = re.sub(r"[?!.,;:]+\s*$", "", (user_input or "").strip())
        m = re.search(r"\b(?:in|em)\s+([a-zA-ZÀ-ÿ0-9\s\-]+)$", base, re.IGNORECASE)
        if m:
            return {"city": m.group(1).strip()}
        return {}

    @staticmethod
    def _weather_forecast_params(user_input: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"days": 2}
        base = re.sub(r"[?!.,;:]+\s*$", "", (user_input or "").strip())
        m = re.search(r"\b(?:in|em)\s+([a-zA-ZÀ-ÿ0-9\s\-]+)$", base, re.IGNORECASE)
        if m:
            params["city"] = m.group(1).strip()
        return params

    @staticmethod
    def _memory_store_params(user_input: str) -> Dict[str, Any]:
        text = user_input.strip()
        return {"category": "general", "content": text}

    @staticmethod
    def _media_query_params(user_input: str) -> Dict[str, Any]:
        text = (user_input or "").strip().lower()
        text = re.sub(r"\b(play|listen|reproduz|reproduzir|reporduz|toca|tocar|ouvir|abre|abrir)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(in|on|at|to|for|no|na|do|da|de|em|para|a|o|uma|um)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(youtube music|ytoutbe music|yt music|youtube|deezer|spotify)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(song|music|musica|música)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" \"'")
        if not text:
            text = user_input.strip()
        return {"query": text}

    @staticmethod
    def _task_create_params(user_input: str) -> Dict[str, Any]:
        cleaned = (user_input or "").strip()
        cleaned = re.sub(
            r"^(create task|new task|criar tarefa|crie uma tarefa|nova tarefa|agendar tarefa|agende uma tarefa)\s*[:\-]?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        if not cleaned:
            return {"name": "New Task", "context": "Task details to be defined."}

        if " para " in cleaned.lower():
            parts = re.split(r"\s+para\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
            name = parts[0].strip().strip("\"'") or "New Task"
            context = parts[1].strip().strip("\"'") if len(parts) > 1 else cleaned
            if not context:
                context = cleaned
            return {"name": name[:120], "context": context[:4000]}

        if ":" in cleaned:
            parts = cleaned.split(":", 1)
            name = parts[0].strip().strip("\"'") or "New Task"
            context = parts[1].strip().strip("\"'") if len(parts) > 1 else cleaned
            if not context:
                context = cleaned
            return {"name": name[:120], "context": context[:4000]}

        words = cleaned.split()
        name = " ".join(words[:6]).strip() or "New Task"
        return {"name": name[:120], "context": cleaned[:4000]}
