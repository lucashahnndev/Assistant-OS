from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from typing import Any, Dict, List, Optional

import requests

from core.intent import AgentIntent
from core.errors import SyntaxError as AgentSyntaxError, ErrorCode
from drivers.llm.base import ILLMProvider
from server.core.secret_manager import resolve_secret_ref
from utils.logging_config import get_logger

logger = get_logger("HuggingFaceDriver")


class HuggingFaceProvider(ILLMProvider):
    """
    Hugging Face provider using OpenAI-compatible chat completions endpoint.
    Default base URL targets HF Router.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.api_key = self._resolve_secret(cfg.get("api_key"))
        self.model = cfg.get("model", "HuggingFaceTB/SmolLM3-3B")
        self.base_url = str(cfg.get("base_url", "https://router.huggingface.co/v1")).rstrip("/")
        self.timeout = float(cfg.get("timeout", 90))
        self.max_tokens = int(cfg.get("max_tokens", 512))
        self.temperature = float(cfg.get("temperature", 0.2))

    @staticmethod
    def _resolve_secret(value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        return resolve_secret_ref(str(value))

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _extract_json(content: str) -> Dict[str, Any] | None:
        text = (content or "").strip()
        if not text:
            return None

        if text.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1).strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[i:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        return None

    def _chat_completion(self, messages: List[Dict[str, Any]], *, max_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(max_tokens if max_tokens is not None else self.max_tokens),
            "temperature": float(self.temperature if temperature is None else temperature),
        }

        response = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()

    def generate_intent(
        self,
        user_input: str,
        history: List[Dict[str, str]],
        system_prompt: str,
        attachments: List[str] | None = None,
        **kwargs
    ) -> AgentIntent:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_input})

        schema_hint = {
            "thought": "Reasoning process",
            "plan": ["Step 1", "Step 2"],
            "action": "capability.action",
            "params": {"key": "value"},
            "response_text": "optional user-facing text",
            "attachments": ["/absolute/path"],
        }
        messages.append(
            {
                "role": "system",
                "content": (
                    "Return ONLY valid JSON following this schema:\n"
                    f"{json.dumps(schema_hint, ensure_ascii=False)}"
                ),
            }
        )

        try:
            content = self._chat_completion(messages)
            data = self._extract_json(content)
            if not data:
                raise AgentSyntaxError(
                    "HuggingFace structured output is not valid JSON.",
                    code=ErrorCode.PLANNER_INVALID_JSON,
                )

            params = data.get("params", {})
            if not isinstance(params, dict):
                params = {}

            out_attachments = data.get("attachments")
            if not out_attachments and isinstance(params, dict):
                out_attachments = params.get("attachments")
            normalized_attachments: Optional[List[str]] = None
            if isinstance(out_attachments, str) and out_attachments.strip():
                normalized_attachments = [out_attachments.strip()]
            elif isinstance(out_attachments, list):
                cleaned = [str(x).strip() for x in out_attachments if str(x).strip()]
                normalized_attachments = cleaned or None

            logger.info(
                "HuggingFace parsed intent | syntax_valid=true action_candidate=%s",
                str(data.get("action", "") or "").strip(),
            )
            return AgentIntent(
                thought=str(data.get("thought", "") or ""),
                plan=data.get("plan", []) if isinstance(data.get("plan", []), list) else [],
                state_summary=data.get("state_summary", {}),
                action=str(data.get("action", "") or "").strip(),
                params=params,
                task_label=data.get("task_label"),
                response_text=str(data.get("response_text", "") or ""),
                attachments=normalized_attachments,
            )
        except Exception as e:
            logger.error(f"HuggingFace generate_intent error: {e}")
            raise e

    def generate_text(self, prompt: str, system_prompt: str = "", **kwargs) -> str:
        messages: List[Dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            return self._chat_completion(messages, max_tokens=min(self.max_tokens, 512), temperature=0.3)
        except Exception as e:
            logger.error(f"HuggingFace generate_text error: {e}")
            raise e

    def analyze_image(self, image_path: str, prompt: str) -> str:
        if not os.path.exists(image_path):
            return f"Error: arquivo não encontrado: {image_path}"

        mime_type, _ = mimetypes.guess_type(image_path)
        mime_type = mime_type or "image/png"
        try:
            with open(image_path, "rb") as f:
                raw = f.read()
            data_url = f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ]
            return self._chat_completion(messages, max_tokens=min(self.max_tokens, 512), temperature=0.1)
        except Exception as e:
            logger.error(f"HuggingFace analyze_image error: {e}")
            raise e
