import re


_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_UNCLOSED_CODE_BLOCK_RE = re.compile(r"```[\s\S]*$", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_UNCLOSED_INLINE_RE = re.compile(r"`[^`]*$")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_URL_RE = re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s<>()\"']+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_LIST_MARKER_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_ORDERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_QUOTE_RE = re.compile(r"^\s*>\s?", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"\|")
_EMPHASIS_RE = re.compile(r"[*_~]")
_WS_RE = re.compile(r"\s+")


def sanitize_voice_text(text: str) -> str:
    """
    Sanitizes markdown/code-heavy content to plain conversational text
    suitable for voice interaction (ASR post-processing + TTS).
    """
    value = str(text or "")
    if not value.strip():
        return ""

    value = _CODE_BLOCK_RE.sub(" ", value)
    value = _UNCLOSED_CODE_BLOCK_RE.sub(" ", value)
    value = _MD_IMAGE_RE.sub(" ", value)
    value = _MD_LINK_RE.sub(r"\1", value)
    value = _INLINE_CODE_RE.sub(" ", value)
    value = _UNCLOSED_INLINE_RE.sub(" ", value)
    value = _HTML_TAG_RE.sub(" ", value)
    value = _HEADING_RE.sub("", value)
    value = _LIST_MARKER_RE.sub("", value)
    value = _ORDERED_LIST_RE.sub("", value)
    value = _QUOTE_RE.sub("", value)
    value = _TABLE_SEP_RE.sub(" ", value)
    value = _EMPHASIS_RE.sub("", value)
    value = value.replace("\\n", " ").replace("\\t", " ")
    value = value.replace("```", " ").replace("`", " ")
    value = _WS_RE.sub(" ", value).strip()
    return value


def sanitize_tts_text(
    text: str,
    *,
    code_block_label: str = "bloco de código",
    inline_code_label: str = "código",
    url_label: str = "link",
) -> str:
    """
    Sanitizes model output for TTS and replaces technical/noisy fragments by
    short speakable labels.
    """
    value = str(text or "")
    if not value.strip():
        return ""

    value = _CODE_BLOCK_RE.sub(f" {code_block_label} ", value)
    value = _UNCLOSED_CODE_BLOCK_RE.sub(f" {code_block_label} ", value)
    value = _MD_IMAGE_RE.sub(" ", value)
    value = _MD_LINK_RE.sub(r"\1", value)
    value = _URL_RE.sub(f" {url_label} ", value)
    value = _INLINE_CODE_RE.sub(f" {inline_code_label} ", value)
    value = _UNCLOSED_INLINE_RE.sub(f" {inline_code_label} ", value)
    value = _HTML_TAG_RE.sub(" ", value)
    value = _HEADING_RE.sub("", value)
    value = _LIST_MARKER_RE.sub("", value)
    value = _ORDERED_LIST_RE.sub("", value)
    value = _QUOTE_RE.sub("", value)
    value = _TABLE_SEP_RE.sub(" ", value)
    value = _EMPHASIS_RE.sub("", value)
    value = value.replace("\\n", " ").replace("\\t", " ")
    value = value.replace("```", f" {code_block_label} ").replace("`", f" {inline_code_label} ")
    value = _WS_RE.sub(" ", value).strip()
    return value


def derive_spoken_name(agent_name: str, spoken_name: str = "") -> str:
    """
    Derives a speech-friendly agent name.
    Priority:
    1) explicit spoken_name (if provided)
    2) auto-normalized from agent_name (e.g. A.T.L.A.S -> atlas)
    """
    explicit = str(spoken_name or "").strip()
    if explicit:
        return explicit

    raw = str(agent_name or "").strip()
    if not raw:
        return ""

    compact = re.sub(r"[^A-Za-z0-9]+", "", raw)
    if not compact:
        return raw

    tokens = re.findall(r"[A-Za-z0-9]+", raw)
    is_acronym_style = len(tokens) >= 2 and all(len(t) == 1 for t in tokens)
    if is_acronym_style:
        return compact.lower()

    return raw


def normalize_agent_name_for_tts(text: str, agent_name: str, spoken_name: str = "") -> str:
    """
    Rewrites agent-name mentions to a speech-friendly form in TTS text.
    Keeps web/chat text untouched; this should be applied only in TTS path.
    """
    value = str(text or "")
    if not value.strip():
        return ""

    base_name = str(agent_name or "").strip()
    if not base_name:
        return value

    spoken = derive_spoken_name(base_name, spoken_name=spoken_name)
    if not spoken:
        return value

    # Exact configured name (case-insensitive)
    value = re.sub(re.escape(base_name), spoken, value, flags=re.IGNORECASE)

    # Acronym-like variants with separators: A.T.L.A.S / A T L A S / A-T-L-A-S
    letters = re.sub(r"[^A-Za-z0-9]+", "", base_name)
    if len(letters) >= 2:
        seq = r"[\s\.\-_]*".join(re.escape(ch) for ch in letters)
        value = re.sub(rf"\b{seq}\b", spoken, value, flags=re.IGNORECASE)

    return value
