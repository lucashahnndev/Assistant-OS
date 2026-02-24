from typing import List, Dict, Any
import json
from openai import OpenAI
from core.intent import AgentIntent
from drivers.llm.base import ILLMProvider
from utils.logging_config import get_logger

logger = get_logger("OpenAIDriver")

class OpenAIChatProvider(ILLMProvider):
    def __init__(self, config: Dict[str, Any] = None):
        if config:
            self.api_key = config.get("api_key")
            self.org_id = config.get("organization_id")
        else:
            from config import ConfigManager
            cfg = ConfigManager().get_llm_config().get("providers", {}).get("openai", {})
            self.api_key = cfg.get("api_key")
            self.org_id = cfg.get("organization_id")

        self.client = OpenAI(
            api_key=self.api_key,
            organization=self.org_id
        )
        self.model = config.get("model", "gpt-4o-mini") if config else "gpt-4o-mini"

    def generate_intent(self, user_input: str, history: List[Dict[str, str]], system_prompt: str, attachments: List[str] = None) -> AgentIntent:
        # Construct messages
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        # Define the function schema for structured output
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_intent",
                    "description": "Execute an action based on the user's request.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "thought": {
                                "type": "string",
                                "description": "The reasoning process before deciding the action."
                            },
                            "action": {
                                "type": "string",
                                "description": "The name of the action to be executed."
                            },
                            "params": {
                                "type": "object",
                                "description": "Parameters required for the action."
                            },
                            "response_text": {
                                "type": "string",
                                "description": "Text to be spoken back to the user immediately."
                            },
                            "attachments": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "A list of absolute file paths to attach to the response when action is 'reply'."
                            }
                        },
                        "required": ["thought", "action", "params"]
                    }
                }
            }
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "execute_intent"}}
            )

            tool_call = response.choices[0].message.tool_calls[0]
            function_args = json.loads(tool_call.function.arguments)

            attachments = function_args.get("attachments")
            if not attachments and isinstance(function_args.get("params"), dict):
                attachments = function_args.get("params", {}).get("attachments")

            return AgentIntent(
                thought=function_args.get("thought", ""),
                action=function_args.get("action", "unknown"),
                params=function_args.get("params", {}),
                response_text=function_args.get("response_text", ""),
                attachments=attachments
            )

        except Exception as e:
            logger.error(f"OpenAI Error: {e}")
            # Fallback intent
            return AgentIntent(
                thought="Error connecting to LLM",
                action="error",
                params={"error": str(e)},
                response_text="I'm having trouble connecting to my brain."
            )

    def generate_text(self, prompt: str, system_prompt: str = "") -> str:
        """Generates plain text using OpenAI's chat completions."""
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
            return response.choices[0].message.content.strip() if response.choices else "Error: Resposta vazia da OpenAI."
        except Exception as e:
            logger.error(f"OpenAI generate_text error: {e}")
            return f"Erro na geração de texto: {e}"
