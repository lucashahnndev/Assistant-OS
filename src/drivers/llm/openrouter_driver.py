from typing import List, Dict, Any
import json
import os
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
                logger.warning("Could not parse JSON intent. Falling back to plain-text reply.")
                return AgentIntent(
                    thought="Model returned non-JSON output.",
                    action="reply",
                    params={},
                    response_text=content
                )

            # VALIDATION & EXTRACTION
            thought = data.get("thought", "").strip() or "Reasoning omitted by model."
            action = data.get("action", "").strip() or "reply"
            
            attachments = data.get("attachments")
            if not attachments and isinstance(data.get("params"), dict):
                attachments = data.get("params", {}).get("attachments")

            return AgentIntent(
                thought=thought,
                plan=data.get("plan", []),
                state_summary=data.get("state_summary", {}),
                action=action,
                params=data.get("params", {}),
                task_label=data.get("task_label"),
                response_text=data.get("response_text", ""),
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
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end < start:
                return None
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError as e:
            logger.error(f"JSON Parse Error: {e.msg}")
            return None

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
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=4096,
                timeout=60.0
            )
            
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
