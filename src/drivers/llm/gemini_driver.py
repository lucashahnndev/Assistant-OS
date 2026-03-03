import os
import json
import logging
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider
from utils.logging_config import get_logger

logger = get_logger("GeminiDriver")

class GeminiProvider(ILLMProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if config:
            self.api_key = config.get("api_key")
            self.model_name = config.get("model", "gemini-2.0-flash")
        else:
            from config.manager import ConfigManager
            cm = ConfigManager()
            providers = cm.get_llm_config().get("providers", {})
            cfg = providers.get("google") or providers.get("gemini", {})
            self.api_key = cfg.get("api_key")
            self.model_name = cfg.get("model", "gemini-2.0-flash")
        
        self.max_tokens = int(config.get("max_tokens", 4096)) if config else 4096
        self.client = genai.Client(api_key=self.api_key)

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] | None = None, **kwargs) -> AgentIntent:
        contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        
        user_parts = [{"text": user_input}]
        contents.append({"role": "user", "parts": user_parts})

        # Structured output prompt
        json_schema = {
            "thought": "Reasoning process",
            "plan": ["Step 1", "Step 2", "..."],
            "action": "Action name",
            "params": {"param_name": "value"},
            "response_text": "Response to user",
            "attachments": ["/absolute/file/path"]
        }

        prompt_suffix = (
            f"\n\nYou MUST respond with a valid JSON object ONLY.\n"
            f"EXPECTED SCHEMA:\n{json.dumps(json_schema, indent=2)}\n"
        )

        try:
            # We use GenerateContentConfig for the newer SDK
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.2, # Lower temperature for more consistent JSON
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens)
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

            if not response.text:
                logger.error("Gemini returned an empty response.")
                return AgentIntent(thought="Empty response", action="reply", params={}, response_text="Erro no cérebro.")

            content = response.text.strip()
            
            # ROBUST JSON EXTRACTION: Find the absolute first { and last }
            data = {}
            try:
                start = content.find('{')
                if start != -1:
                    # Attempt to parse from start to the end of the first valid JSON object
                    # We use a greedy approach for the last brace first
                    end = content.rfind('}')
                    if end != -1:
                        json_str = content[start:end+1]
                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError as je:
                            # If it fails with "Extra data", try to truncate at the specific position
                            # JSONDecodeError.pos is 0-indexed position in the input string
                            # but we need to find it within our sliced json_str
                            msg = str(je)
                            if "Extra data" in msg:
                                # Simple truncation attempt if the error tells us where the extra data starts
                                try:
                                    # je.pos is the index in json_str where extra data begins
                                    data = json.loads(json_str[:je.pos])
                                except:
                                    logger.warning("Recursive JSON fix failed.")
                                    raise je
                            else:
                                raise je
                else:
                    logger.warning("No JSON braces found in Gemini response. Falling back to text.")
                    return AgentIntent(
                        thought="Model returned plain text.",
                        action="reply",
                        params={},
                        response_text=content
                    )
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse Gemini JSON. Content Start: {content[:100]}")
                if len(content) > 0 and not content.startswith('{'):
                    return AgentIntent(
                        thought="Treating invalid JSON as plain text reply.",
                        action="reply",
                        params={},
                        response_text=content
                    )
                raise

            attachments = data.get("attachments")
            if not attachments and isinstance(data.get("params"), dict):
                attachments = data.get("params", {}).get("attachments")

            return AgentIntent(
                thought=data.get("thought", ""),
                plan=data.get("plan", []),
                action=data.get("action", "reply"), # Default to reply
                params=data.get("params", {}),
                response_text=data.get("response_text", data.get("reply", "")),
                attachments=attachments
            )

        except Exception as e:
            logger.error(f"Gemini Error: {e}")
            raise e

    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        """Generates plain text using the Flash model."""
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                max_output_tokens=kwargs.get("max_tokens", self.max_tokens)
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt],
                config=config
            )
            return response.text.strip() if response.text else "Error: Resposta vazia do Gemini."
        except Exception as e:
            logger.error(f"Gemini generate_text error: {e}")
            raise e

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        Directly analyzes an image using Gemini.
        """
        if not os.path.exists(image_path):
            return f"Error: Arquivo não encontrado: {image_path}"
            
        try:
            import mimetypes
            mime_type, _ = mimetypes.guess_type(image_path)
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            
            content = [
                types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/png")
            ]
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=content,
                config=types.GenerateContentConfig(temperature=0.4)
            )
            
            return response.text or "O modelo não retornou nenhuma descrição."
        except Exception as e:
            logger.error(f"Gemini Vision Error: {e}")
            raise e
