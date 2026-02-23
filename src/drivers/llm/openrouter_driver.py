from typing import List, Dict, Any, Optional, Tuple
import json
import os
import re
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider
from config import ConfigManager
from utils.logging_config import get_logger

logger = get_logger("OpenRouterDriver")

class OpenRouterProvider(ILLMProvider):
    def __init__(self, config: Dict[str, Any]):
        # OpenRouter uses the same library/protocol as OpenAI
        self.api_key = config.get('api_key')
        self.model = config.get('model', 'openai/gpt-3.5-turbo') # Default
        
        if not self.api_key:
             # Try to get from global config if not passed specifically
             cm = ConfigManager()
             self.api_key = cm.get('openrouter', {}).get('api_key')

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
        # Vision models on free/low-credit accounts frequently fail with high max_tokens.
        # Keep a conservative default and allow override per provider config.
        self.vision_max_tokens = int(config.get("vision_max_tokens", config.get("max_tokens", 512)))

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] = None) -> AgentIntent:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        logger.info(f"OpenRouter Request Started | Model: {self.model} | History: {len(history)} messages")

        try:
            # We remove 'tools' and 'tool_choice' to support generic models
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                timeout=60.0,
                extra_headers={
                    "HTTP-Referer": "https://github.com/lucas-openclaw/aosd", # Optional: Change to your site
                    "X-Title": "Atlas Bot"
                }
            )

            if not response.choices or not response.choices[0].message.content:
                logger.error("OpenRouter returned an empty response.")
                return AgentIntent(
                    thought="Model returned empty response.",
                    action="reply",
                    params={},
                    response_text="Desculpe, meu cérebro está um pouco lento agora. Pode repetir?"
                )

            content = response.choices[0].message.content.strip()
            logger.info(f"Raw LLM Response (Len: {len(content)}): {content[:100]}...")
            
            data = self._extract_json(content)
            if data is None:
                recovered_intent = self._recover_from_plain_text(user_input=user_input, content=content)
                if recovered_intent:
                    logger.warning(
                        "Could not parse JSON intent. Recovered plain-text output into structured intent | Action: %s",
                        recovered_intent.action,
                    )
                    return recovered_intent

                logger.warning("Could not parse JSON intent. Falling back to plain-text reply.")
                return AgentIntent(
                    thought="Model returned non-JSON output.",
                    action="reply",
                    params={},
                    response_text=content
                )

            # VALIDATION & EXTRACTION
            thought = data.get("thought", "").strip() or "Reasoning omitted by model."
            action = data.get("action", "").strip()
            params = data.get("params", {})
            response_text = data.get("response_text", "")

            # When malformed JSON is partially parsed (e.g., only "thought"),
            # avoid defaulting blindly to "reply" with empty text.
            if not action:
                hint_chunks = [thought, str(response_text or "")]
                try:
                    if isinstance(params, dict) and params:
                        hint_chunks.append(json.dumps(params, ensure_ascii=False))
                except Exception:
                    pass
                hint_text = " ".join([chunk for chunk in hint_chunks if chunk]).strip()
                inferred_action, inferred_params = self._infer_action_and_params(user_input, hint_text)
                if inferred_action:
                    action = inferred_action
                    if not isinstance(params, dict) or not params:
                        params = inferred_params
                else:
                    action = "reply"

            # Additional guard: "reply" with no user-facing text but with operational thought.
            # Try recovering an action from thought/user_input to keep tasks progressing.
            if action == "reply" and not response_text:
                inferred_action, inferred_params = self._infer_action_and_params(user_input, thought)
                if inferred_action and inferred_action != "reply":
                    action = inferred_action
                    if not isinstance(params, dict) or not params:
                        params = inferred_params
            
            attachments = data.get("attachments")
            if not attachments and isinstance(params, dict):
                attachments = params.get("attachments")

            return AgentIntent(
                thought=thought,
                plan=data.get("plan", []),
                state_summary=data.get("state_summary", {}),
                action=action,
                params=params if isinstance(params, dict) else {},
                task_label=data.get("task_label"),
                response_text=response_text,
                attachments=attachments
            )

        except Exception as e:
            logger.error(f"OpenRouter Error: {e}")
            return AgentIntent(
                thought="Connection Error",
                action="error",
                params={"error": str(e)},
                response_text="I can't reach the cloud brain."
            )

    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any] | None:
        """Extracts and parses the first JSON object found in model output."""
        if not isinstance(content, str):
            return None

        text = content.strip()
        if not text:
            return None

        # Common model pattern: fenced JSON block
        if text.startswith("```"):
            fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
            if fence_match:
                text = fence_match.group(1).strip()

        # Fast path: pure JSON string
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e:
            logger.error(f"JSON Parse Error: {e.msg}")

        # Robust path: scan for the first decodable object in mixed text
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _looks_like_internal_reasoning(content: str) -> bool:
        text = (content or "").strip().lower()
        if not text:
            return False

        # Typical private chain-of-thought style markers
        if text.startswith("o usuário") or text.startswith("o usuario") or text.startswith("the user"):
            return True

        # Progress/operation stubs are not final user-facing replies.
        if text.startswith(("pesquisando", "procurando", "buscando", "abrindo", "executando", "aguarde", "um momento")):
            return True

        reasoning_cues = [
            "vou usar",
            "i will use",
            "my plan",
            "plano:",
            "action:",
            "ação",
            "acao",
            "params",
        ]
        return any(cue in text for cue in reasoning_cues)

    @staticmethod
    def _looks_like_user_facing_final(content: str) -> bool:
        text = (content or "").strip().lower()
        if not text:
            return False
        # Typical final-answer markers (tables/lists/markdown/reporting style).
        markers = [
            "**título",
            "**titulo",
            "**artista",
            "**álbum",
            "**album",
            "veja os detalhes",
            "a música",
            "a musica",
            "está sendo reproduzida",
            "esta sendo reproduzida",
            "resultado",
            "link:",
            "url:",
        ]
        if any(m in text for m in markers):
            return True
        if "\n- " in text or "\n1." in text:
            return True
        return False

    @staticmethod
    def _extract_query_from_text(user_input: str, content: str) -> str:
        # Prefer explicit query fields if the model included one in plain text.
        for pattern in (
            r'["\']query["\']\s*:\s*["\']([^"\']+)["\']',
            r'["\']q["\']\s*:\s*["\']([^"\']+)["\']',
        ):
            match = re.search(pattern, content or "", flags=re.IGNORECASE)
            if match and match.group(1).strip():
                return match.group(1).strip()

        return (user_input or "").strip()

    @classmethod
    def _infer_action_and_params(cls, user_input: str, content: str) -> Tuple[Optional[str], Dict[str, Any]]:
        text = (content or "").strip()
        lower_text = text.lower()
        lower_user = (user_input or "").strip().lower()
        combined = f"{lower_user} {lower_text}".strip()

        # Explicit action id in plain text (e.g. "action: youtube.search.find")
        explicit_action = re.search(
            r"(?:action|ação|acao)\s*[:=]?\s*['\"`]?([a-z0-9_]+(?:\.[a-z0-9_]+){1,})['\"`]?",
            lower_text,
            flags=re.IGNORECASE,
        )
        if explicit_action:
            action_id = explicit_action.group(1)
            if action_id in {"reply", "error"}:
                return action_id, {}
            if action_id == "browser.automator.control":
                query_text = cls._extract_query_from_text(user_input, text).lower()
                if any(token in query_text for token in ("pause", "pausa", "pausar")):
                    return action_id, {"action": "pause"}
                if any(token in query_text for token in ("next", "próxima", "proxima", "avançar", "avancar")):
                    return action_id, {"action": "next"}
                if any(token in query_text for token in ("mute", "mudo", "silenciar")):
                    return action_id, {"action": "mute"}
                if any(token in query_text for token in ("fullscreen", "tela cheia")):
                    return action_id, {"action": "fullscreen"}
                return action_id, {"action": "play"}
            return action_id, {"query": cls._extract_query_from_text(user_input, text)}

        search_cues = ("buscar", "busca", "search", "procur", "encontr", "pesquis")
        has_search_cue = any(cue in combined for cue in search_cues)
        media_open_cues = ("abre", "abrir", "abrindo", "toca", "tocar", "play", "reproduz", "reproduzir", "música", "musica")
        has_media_open_cue = any(cue in combined for cue in media_open_cues)

        provider_routes = [
            ("youtube", "youtube.search.find"),
            ("deezer", "deezer.search.search"),
            ("spotify", "spotify.search.search"),
            ("wikipedia", "wikipedia.search"),
            ("wikipédia", "wikipedia.search"),
            ("wiki", "wikipedia.search"),
            ("web", "web.search.discover"),
            ("google", "web.search.discover"),
        ]

        for token, action_id in provider_routes:
            if token in combined and has_search_cue:
                return action_id, {"query": cls._extract_query_from_text(user_input, text)}

        # Media-intent fallback: user asked to open/play media on provider, even if model answered only "Pesquisando..."
        if "deezer" in combined and has_media_open_cue:
            return "deezer.search.search", {"query": cls._extract_query_from_text(user_input, text)}
        if "spotify" in combined and has_media_open_cue:
            return "spotify.search.search", {"query": cls._extract_query_from_text(user_input, text)}
        if ("youtube" in combined or "yt" in combined) and has_media_open_cue:
            return "youtube.search.find", {"query": cls._extract_query_from_text(user_input, text)}

        return None, {}

    @classmethod
    def _recover_from_plain_text(cls, user_input: str, content: str) -> Optional[AgentIntent]:
        text = (content or "").strip()
        if not text:
            return None

        # If model already produced a user-facing final answer, don't force it back into tool actions.
        if cls._looks_like_user_facing_final(text):
            return None

        # If model output is user-facing plain text, keep old behavior.
        if not cls._looks_like_internal_reasoning(text):
            return None

        action_id, params = cls._infer_action_and_params(user_input, text)
        if action_id:
            return AgentIntent(
                thought=text,
                action=action_id,
                params=params,
                response_text=None,
            )

        # Mark as unknown to trigger resolver fallback instead of exposing internal monologue as final reply.
        return AgentIntent(
            thought=text,
            action="unknown",
            params={"fallback_reason": "non_json_internal_reasoning"},
            response_text=None,
        )

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Directly analyzes an image using OpenRouter.
        """
        logger.info(f"Vision Request: Image={image_path} | Model={self.model}")
        if not os.path.exists(image_path):
            logger.error(f"Vision File Not Found: {image_path}")
            return f"Erro: Arquivo não encontrado: {image_path}"
            
        try:
            import base64
            import mimetypes
            
            mime_type, _ = mimetypes.guess_type(image_path)
            with open(image_path, "rb") as f:
                encoded_image = base64.b64encode(f.read()).decode('utf-8')
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type or 'image/png'};base64,{encoded_image}"
                            }
                        }
                    ]
                }
            ]

            def _request_with_tokens(max_tokens: int):
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    timeout=60.0
                )

            try:
                response = _request_with_tokens(self.vision_max_tokens)
            except Exception as first_exc:
                # Credit-aware retry for OpenRouter 402 messages:
                # "...requested up to X tokens, but can only afford Y..."
                err_text = str(first_exc)
                affordable_match = re.search(r"can only afford\s+(\d+)", err_text, flags=re.IGNORECASE)
                if affordable_match:
                    affordable = max(64, int(affordable_match.group(1)))
                    retry_tokens = min(self.vision_max_tokens, affordable)
                    if retry_tokens < self.vision_max_tokens:
                        logger.warning(
                            "Vision request exceeded credits. Retrying with lower max_tokens=%s (affordable=%s).",
                            retry_tokens,
                            affordable,
                        )
                        response = _request_with_tokens(retry_tokens)
                    else:
                        raise
                else:
                    raise

            if response.choices and response.choices[0].message.content:
                return response.choices[0].message.content.strip()
            return "O modelo não retornou nenhuma descrição."
        except Exception as e:
            logger.error(f"OpenRouter Vision Error: {e}")
            return f"Erro na análise de visão: {e}"

    def generate_text(self, prompt: str, system_prompt: str = "") -> str:
        """Generates plain text using OpenRouter."""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3
            )
            return response.choices[0].message.content.strip() if response.choices else "Erro: Resposta vazia do OpenRouter."
        except Exception as e:
            logger.error(f"OpenRouter generate_text error: {e}")
            return f"Erro na geração de texto: {e}"
