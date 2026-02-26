import re
from typing import List


class QuerySemantics:
    _LEADING_NOISE = re.compile(
        r"^(?:por favor[,:\s]*)?(?:pode(?:ria)?\s+)?(?:me\s+)?"
        r"(?:(?:ajuda(?:r)?|auxilia(?:r)?)(?:\s+a)?\s+)?",
        re.IGNORECASE,
    )
    _LEADING_COMMAND = re.compile(
        r"^(?:encontra(?:r)?|encontre|procura(?:r)?|procure|pesquisa(?:r)?|pesquise|"
        r"busca(?:r)?|busque|acha(?:r)?|"
        r"find|search|look\s*up|lookup)\b[\s:,-]*",
        re.IGNORECASE,
    )
    _ARTICLE = re.compile(r"^(?:o|a|os|as|um|uma)\s+", re.IGNORECASE)
    _SPACES = re.compile(r"\s+")
    _SUMMARY_TAIL = re.compile(
        r"(?:\s*(?:,|;)?\s*(?:e|and)\s+)?"
        r"(?:forne[cç]a|fornecer|traga|d[eê]|fa[cç]a|resuma|sumarize|summarize)\s+"
        r"(?:um|uma|o|a)?\s*"
        r"(?:resumo|sum[aá]rio|summary|explica[cç][aã]o|explanation)\b.*$",
        re.IGNORECASE,
    )

    @classmethod
    def sanitize(cls, text: str) -> str:
        clean = str(text or "").strip().strip("\"'`")
        clean = cls._SPACES.sub(" ", clean)
        return clean

    @classmethod
    def rewrite_for_web(cls, query: str) -> str:
        clean = cls._strip_instruction_shell(query)
        clean = re.sub(r"^(?:sobre|about)\s+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(
            r"\b(?:na|no|pela?|por)\s+(?:web|internet|duckduckgo|google|bing|wikipedia)\b",
            " ",
            clean,
            flags=re.IGNORECASE,
        )
        clean = cls._SPACES.sub(" ", clean).strip(" ,.-")
        return clean or cls.sanitize(query)

    @classmethod
    def rewrite_for_wikipedia(cls, query: str) -> str:
        clean = cls._strip_instruction_shell(query)
        clean = re.sub(r"\b(?:na|no)\s+wikip[eé]dia\b", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\b(?:wikip[eé]dia|wiki)\b\s*(?:sobre|about|:)?", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"^(?:sobre|about)\s+", "", clean, flags=re.IGNORECASE)
        clean = cls._SUMMARY_TAIL.sub("", clean).strip()
        clean = re.sub(r"\b(?:e|and)\s*$", "", clean, flags=re.IGNORECASE).strip()
        clean = cls._SPACES.sub(" ", clean).strip(" ,.-")
        return clean or cls.sanitize(query)

    @classmethod
    def rewrite_for_maps(cls, query: str) -> str:
        clean = cls._strip_instruction_shell(query)
        clean = re.sub(
            r"^(?:o|a|um|uma)?\s*(?:link|url|endere[cç]o|localiza(?:[cç][aã]o|cao)|rota)\s+"
            r"(?:do|da|de)\s+(?:google\s+)?maps?\s+(?:do|da|de|para)\s+",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"\b(?:no|na)\s+(?:google\s+)?maps?\b", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\b(?:link|url)\s+de\s+(?:google\s+)?maps?\s+(?:do|da|de)\s+", "", clean, flags=re.IGNORECASE)
        clean = cls._SPACES.sub(" ", clean).strip(" ,.-")
        return clean or cls.sanitize(query)

    @classmethod
    def likely_maps_intent(cls, query: str) -> bool:
        q = cls.sanitize(query).lower()
        if not q:
            return False
        markers = ("maps", "google maps", "endereço", "localização", "rota", "perto de", "link de maps")
        return any(marker in q for marker in markers)

    @classmethod
    def web_variants(cls, query: str, limit: int = 3) -> List[str]:
        base = cls.sanitize(query)
        rewritten_web = cls.rewrite_for_web(base)
        variants = [rewritten_web]
        if cls.likely_maps_intent(base):
            variants.insert(0, cls.rewrite_for_maps(base))
        if rewritten_web != base:
            variants.append(base)

        out: List[str] = []
        seen = set()
        for v in variants:
            key = cls.sanitize(v).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(cls.sanitize(v))
            if len(out) >= max(1, int(limit)):
                break
        return out or [base]

    @classmethod
    def _strip_instruction_shell(cls, query: str) -> str:
        text = cls.sanitize(query)
        if not text:
            return ""
        for _ in range(3):
            updated = cls._LEADING_NOISE.sub("", text).strip()
            updated = cls._LEADING_COMMAND.sub("", updated).strip()
            updated = cls._ARTICLE.sub("", updated).strip()
            if updated == text:
                break
            text = updated
        return text
