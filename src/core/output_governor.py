from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict


@dataclass(frozen=True)
class OutputGovernanceResult:
    accepted: bool
    envelope_kind: str
    text: str
    rejection_reason: str
    expected_language: str
    detected_language: str
    retry_instruction: str


class OutputGovernor:
    _META_PATTERNS = (
        re.compile(r"\bthe user seems to\b", re.IGNORECASE),
        re.compile(r"\bpreparing to respond\b", re.IGNORECASE),
        re.compile(r"\breturn only the final answer\b", re.IGNORECASE),
        re.compile(r"\b(i am|i'm)\s+analy[sz]ing\b", re.IGNORECASE),
        re.compile(r"\b(i am|i'm)\s+planning\b", re.IGNORECASE),
        re.compile(r"\banalysis\b", re.IGNORECASE),
        re.compile(r"\bparece que o usu[aá]rio\b", re.IGNORECASE),
        re.compile(r"\bestou analisando\b", re.IGNORECASE),
        re.compile(r"\bpreparando resposta\b", re.IGNORECASE),
        re.compile(r"\bestou planejando\b", re.IGNORECASE),
    )

    _PREFIX_PATTERNS = (
        re.compile(r"^\s*(answer|reply|final answer|response|resposta|resposta final|resposta:|answer:)\s*:\s*", re.IGNORECASE),
        re.compile(r"^\s*(answer|reply|final answer|response|resposta|resposta final)\s*-\s*", re.IGNORECASE),
    )

    @classmethod
    def classify_final_user_response(
        cls,
        *,
        user_input: str,
        response_text: str,
        session_language: str = "",
    ) -> OutputGovernanceResult:
        text = cls._strip_response_prefixes(str(response_text or "").strip())
        expected_language = cls._normalize_language(session_language) or cls._normalize_language(
            cls.detect_language(user_input)
        )
        if not text:
            return OutputGovernanceResult(
                accepted=False,
                envelope_kind="classified_error",
                text="",
                rejection_reason="invalid_format",
                expected_language=expected_language,
                detected_language="",
                retry_instruction="Return only the final answer.",
            )

        if cls._contains_meta_reasoning(text):
            return OutputGovernanceResult(
                accepted=False,
                envelope_kind="classified_error",
                text="",
                rejection_reason="thought_leak",
                expected_language=expected_language,
                detected_language=cls.detect_language(text),
                retry_instruction="Return only the final answer. Do not include analysis.",
            )

        detected_language = cls.detect_language(text)
        if expected_language and detected_language and expected_language != detected_language:
            return OutputGovernanceResult(
                accepted=False,
                envelope_kind="classified_error",
                text="",
                rejection_reason="language_mismatch",
                expected_language=expected_language,
                detected_language=detected_language,
                retry_instruction="Respond in the same language as the user.",
            )

        return OutputGovernanceResult(
            accepted=True,
            envelope_kind="final_user_response",
            text=text,
            rejection_reason="",
            expected_language=expected_language,
            detected_language=detected_language,
            retry_instruction="",
        )

    @staticmethod
    def minimal_retry_prompt(user_input: str, draft_text: str, retry_instruction: str) -> tuple[str, str]:
        system_prompt = retry_instruction.strip() or "Return only the final answer."
        prompt = (
            f"User input:\n{str(user_input or '').strip()}\n\n"
            f"Draft answer:\n{str(draft_text or '').strip()}\n\n"
            "Return only the final answer."
        )
        return system_prompt, prompt

    @staticmethod
    def detect_language(text: str) -> str:
        value = str(text or "").strip().lower()
        if not value:
            return ""
        if re.search(r"[\u4e00-\u9fff]", value):
            return "zh"
        if re.search(r"[\u0600-\u06ff]", value):
            return "ar"

        pt_hits = 0
        en_hits = 0
        if re.search(r"[ãõçáàâéêíóôú]", value):
            pt_hits += 2
        if re.search(r"\b(ol[aá]|oi|você|voce|obrigado|precisa|quero|como|por favor|resposta)\b", value):
            pt_hits += 2
        if re.search(r"\b(the|and|you|please|reply|answer|because|what|how|can|would)\b", value):
            en_hits += 2
        if re.search(r"\b(hello|hi|thanks|please)\b", value):
            en_hits += 1
        if pt_hits > en_hits:
            return "pt"
        if en_hits > pt_hits:
            return "en"
        return ""

    @classmethod
    def _contains_meta_reasoning(cls, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        lowered = value.lower()
        if lowered.startswith(("analysis:", "analysis -", "thinking:", "thought:")):
            return True
        return any(pattern.search(value) for pattern in cls._META_PATTERNS)

    @classmethod
    def _strip_response_prefixes(cls, text: str) -> str:
        value = str(text or "").strip()
        for pattern in cls._PREFIX_PATTERNS:
            value = pattern.sub("", value)
        return value.strip()

    @staticmethod
    def _normalize_language(language: str) -> str:
        value = str(language or "").strip().lower()
        if value.startswith("pt"):
            return "pt"
        if value.startswith("en"):
            return "en"
        if value.startswith("zh"):
            return "zh"
        if value.startswith("ar"):
            return "ar"
        return ""
