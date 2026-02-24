from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, TypeVar, overload

from openai import APIConnectionError, APIStatusError, RateLimitError
from openai.types.shared_params.response_format_json_schema import (
    JSONSchema,
    ResponseFormatJSONSchema,
)
from pydantic import BaseModel

from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use.llm.openrouter.serializer import OpenRouterMessageSerializer
from browser_use.llm.schema import SchemaOptimizer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar("T", bound=BaseModel)


@dataclass
class ChatOpenRouterSystemRole(ChatOpenRouter):
    """
    Compatibility wrapper for providers that reject developer-role instructions.
    It enforces system role semantics on instruction messages.
    """

    # instruction_mode:
    # - "system_role": normalize developer -> system
    # - "user_only": move all system/developer instruction to first user message
    instruction_mode: str = "system_role"

    @staticmethod
    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    txt = str(part.get("text") or "").strip()
                    if txt:
                        parts.append(txt)
            return "\n".join(parts).strip()
        return str(content or "").strip()

    @classmethod
    def _normalize_roles(cls, openrouter_messages: list[dict[str, Any]], instruction_mode: str) -> list[dict[str, Any]]:
        mode = str(instruction_mode or "system_role").strip().lower()
        normalized: list[dict[str, Any]] = []
        instruction_blocks: list[str] = []

        for i, msg in enumerate(openrouter_messages):
            item = dict(msg)
            role = str(item.get("role") or "").strip().lower()
            if role in {"developer", "system"}:
                text = cls._content_to_text(item.get("content"))
                if text:
                    instruction_blocks.append(text)
                if mode == "user_only":
                    # Drop system/developer messages and inject instructions into user later.
                    continue
                if role == "developer":
                    item["role"] = "system"
                    role = "system"

            # Defensive fallback: ensure first instruction-like message is system.
            if i == 0 and role not in {"system", "user", "assistant", "tool"}:
                item["role"] = "system"
            normalized.append(item)

        if mode != "user_only" or not instruction_blocks:
            return normalized

        instruction_text = (
            "Instruction context:\n"
            + "\n\n".join(instruction_blocks).strip()
        )

        # Prepend instruction text to first user message; preserve image parts if present.
        for msg in normalized:
            if str(msg.get("role") or "").strip().lower() != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = f"{instruction_text}\n\n{content}".strip()
            elif isinstance(content, list):
                msg["content"] = [{"type": "text", "text": instruction_text}] + content
            else:
                msg["content"] = instruction_text
            return normalized

        # No user message available: inject one up front.
        normalized.insert(0, {"role": "user", "content": instruction_text})
        return normalized

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s, flags=re.DOTALL)
            s = re.sub(r"\s*```$", "", s, flags=re.DOTALL)
        return s.strip()

    @classmethod
    def _sanitize_json_payload(cls, content: str) -> str:
        raw = cls._strip_code_fences(content)
        if not raw:
            return raw
        # Fast path
        try:
            json.loads(raw)
            return raw
        except Exception:
            pass

        # Try to extract first JSON object/array window from noisy text.
        starts = [i for i, ch in enumerate(raw) if ch in "{["]
        for start in starts:
            candidate = raw[start:].strip()
            if not candidate:
                continue
            for end in range(len(candidate), 1, -1):
                probe = candidate[:end].strip()
                if not probe:
                    continue
                try:
                    parsed = json.loads(probe)
                    return json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    continue
        return raw

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: None = None, **kwargs: Any
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T], **kwargs: Any
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: Any
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        openrouter_messages = OpenRouterMessageSerializer.serialize_messages(messages)
        openrouter_messages = self._normalize_roles(openrouter_messages, self.instruction_mode)

        extra_headers = {}
        if self.http_referer:
            extra_headers["HTTP-Referer"] = self.http_referer

        try:
            if output_format is None:
                response = await self.get_client().chat.completions.create(
                    model=self.model,
                    messages=openrouter_messages,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    seed=self.seed,
                    extra_headers=extra_headers,
                    **(self.extra_body or {}),
                )
                usage = self._get_usage(response)
                return ChatInvokeCompletion(
                    completion=response.choices[0].message.content or "",
                    usage=usage,
                )

            schema = SchemaOptimizer.create_optimized_json_schema(output_format)
            response_format_schema: JSONSchema = {
                "name": "agent_output",
                "strict": True,
                "schema": schema,
            }
            response = await self.get_client().chat.completions.create(
                model=self.model,
                messages=openrouter_messages,
                temperature=self.temperature,
                top_p=self.top_p,
                seed=self.seed,
                response_format=ResponseFormatJSONSchema(
                    json_schema=response_format_schema,
                    type="json_schema",
                ),
                extra_headers=extra_headers,
                **(self.extra_body or {}),
            )

            content = response.choices[0].message.content
            if content is None:
                raise ModelProviderError(
                    message="Failed to parse structured output from model response",
                    status_code=500,
                    model=self.name,
                )

            usage = self._get_usage(response)
            try:
                parsed = output_format.model_validate_json(content)
            except Exception:
                sanitized = self._sanitize_json_payload(content)
                parsed = output_format.model_validate_json(sanitized)
            return ChatInvokeCompletion(completion=parsed, usage=usage)

        except RateLimitError as e:
            raise ModelRateLimitError(message=e.message, model=self.name) from e
        except APIConnectionError as e:
            raise ModelProviderError(message=str(e), model=self.name) from e
        except APIStatusError as e:
            raise ModelProviderError(message=e.message, status_code=e.status_code, model=self.name) from e
        except Exception as e:
            raise ModelProviderError(message=str(e), model=self.name) from e
