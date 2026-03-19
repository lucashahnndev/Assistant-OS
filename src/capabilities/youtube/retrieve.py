import json
import re
import subprocess
from datetime import datetime
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import httpx

from ..base import CapabilityBase
from ..shared.error_contract import error_envelope, success_envelope
from ..shared.google_auth import resolve_google_request_auth
from server.core.secret_manager import resolve_secret_ref


def _clamp_max_chars(value: Any, default: int = 12000) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(100, min(n, 50000))


def _truncate(text: Any, max_chars: int) -> str:
    content = str(text or "").strip()
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 1].rstrip() + "…"


def _normalize_ws(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _parse_video_id_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if "youtu.be" in host:
            parts = [p for p in parsed.path.split("/") if p]
            return parts[0] if parts else None
        if "youtube.com" in host:
            query = parse_qs(parsed.query)
            if query.get("v"):
                return query["v"][0]
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in {"shorts", "live"}:
                return parts[1]
    except Exception:
        return None
    return None


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _pick_caption_url(meta: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    subtitles = meta.get("automatic_captions") or {}
    if not isinstance(subtitles, dict) or not subtitles:
        subtitles = meta.get("subtitles") or {}
    if not isinstance(subtitles, dict):
        return None, None

    preferred_langs = ["en", "en-US", "pt", "pt-BR", "es"]
    checked = []

    for lang in preferred_langs + list(subtitles.keys()):
        if lang in checked:
            continue
        checked.append(lang)
        tracks = subtitles.get(lang)
        if not isinstance(tracks, list):
            continue
        for t in tracks:
            if not isinstance(t, dict):
                continue
            ext = str(t.get("ext") or "").lower()
            if ext in {"vtt", "srv3", "srv2", "srv1", "json3", "ttml"} and t.get("url"):
                return str(t.get("url")), str(lang)
        for t in tracks:
            if isinstance(t, dict) and t.get("url"):
                return str(t.get("url")), str(lang)

    return None, None


def _vtt_to_text(raw: str) -> str:
    lines = []
    for line in str(raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("WEBVTT"):
            continue
        if "-->" in s:
            continue
        if re.match(r"^\d+$", s):
            continue
        lines.append(s)
    return _normalize_ws(" ".join(lines))


def _parse_published(upload_date: Any) -> Optional[str]:
    date_s = str(upload_date or "").strip()
    if not date_s:
        return None
    if re.match(r"^\d{8}$", date_s):
        try:
            dt = datetime.strptime(date_s, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return date_s
    return date_s


class YouTubeRetrieveCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "youtube"

    @property
    def name(self) -> str:
        return "youtube_retrieve"

    @property
    def actions(self) -> List[str]:
        return ["retrieve.get"]

    def _defaults(self) -> Dict[str, Any]:
        return self.config.get("defaults", {}) if isinstance(self.config, dict) else {}

    def _get_api_key(self) -> Optional[str]:
        api_key = resolve_secret_ref(self.config.get("apiKey"))
        return str(api_key or "").strip() or None

    @staticmethod
    def _fetch_video_via_api(video_id: str, auth: Dict[str, Any], timeout_seconds: float = 8.0) -> Optional[Dict[str, Any]]:
        if not video_id:
            return None
        try:
            with httpx.Client(timeout=httpx.Timeout(max(2.0, min(20.0, timeout_seconds)))) as client:
                resp = client.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "part": "snippet,contentDetails",
                        "id": video_id,
                        **(auth.get("params") or {}),
                    },
                    headers=auth.get("headers") or {},
                )
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400 or not isinstance(data, dict):
                return None
            items = data.get("items") if isinstance(data.get("items"), list) else []
            if not items:
                return None
            item = items[0] if isinstance(items[0], dict) else {}
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            return {
                "title": snippet.get("title"),
                "channel": snippet.get("channelTitle"),
                "description": snippet.get("description"),
                "published_at": snippet.get("publishedAt"),
                "language": snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage"),
            }
        except Exception:
            return None

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        started = perf_counter()
        action = action_id.split(".")[-1]
        if action != "get":
            return error_envelope(
                provider="youtube.retrieve",
                error_code="UNKNOWN_ACTION",
                error_message=f"Unknown youtube.retrieve action: {action_id}",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
                warnings=[],
            )

        defaults = self._defaults()
        include_transcript = bool(
            params.get("include_transcript")
            if params.get("include_transcript") is not None
            else defaults.get("include_transcript", False)
        )
        max_chars = _clamp_max_chars(params.get("max_chars") or defaults.get("max_chars") or 12000)
        transcript_timeout_ms = int(params.get("transcript_timeout_ms") or defaults.get("transcript_timeout_ms") or 8000)
        input_url = str(params.get("url") or "").strip()
        input_video_id = str(params.get("video_id") or "").strip()
        api_key = self._get_api_key()
        auth = resolve_google_request_auth(
            context=context or {},
            kernel=self.kernel,
            api_key_fallback=api_key,
            requested_source=self.config.get("authSource"),
        )

        video_id = input_video_id
        if not video_id and input_url:
            video_id = _parse_video_id_from_url(input_url) or ""

        if not input_url and video_id:
            input_url = _video_url(video_id)

        if not input_url:
            payload = error_envelope(
                provider="youtube.retrieve",
                error_code="MISSING_URL_OR_VIDEO_ID",
                error_message="Provide 'url' or 'video_id'.",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"url": None, "video_id": None})
            return payload

        cmd = ["yt-dlp", "--dump-single-json", "--no-warnings", input_url]
        try:
            proc = subprocess.run(cmd, capture_output=True, message=True, check=True)
        except subprocess.CalledProcessError as e:
            api_fallback = self._fetch_video_via_api(video_id, auth)
            if api_fallback:
                payload = success_envelope(
                    provider="youtube.retrieve_oauth" if auth.get("mode") == "oauth" else "youtube.retrieve",
                    elapsed=int((perf_counter() - started) * 1000),
                    warnings=[
                        "yt-dlp failed; metadata resolved via YouTube Data API.",
                        "Transcript is unavailable in API fallback path.",
                    ],
                )
                payload.update(
                    {
                        "url": input_url,
                        "video_id": video_id or None,
                        "title": api_fallback.get("title"),
                        "channel": api_fallback.get("channel"),
                        "published_at": api_fallback.get("published_at"),
                        "language": api_fallback.get("language"),
                        "description": _truncate(api_fallback.get("description") or "", max_chars),
                        "transcript": None,
                        "transcript_available": False,
                        "transcript_error_code": "TRANSCRIPT_UNAVAILABLE",
                    }
                )
                return payload
            payload = error_envelope(
                provider="youtube.retrieve",
                error_code="YTDLP_ERROR",
                error_message=_truncate(e.stderr or e.stdout or str(e), 500),
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"url": input_url, "video_id": video_id or None})
            return payload
        except FileNotFoundError:
            payload = error_envelope(
                provider="youtube.retrieve",
                error_code="YTDLP_NOT_FOUND",
                error_message="yt-dlp not found in PATH.",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"url": input_url, "video_id": video_id or None})
            return payload

        try:
            meta = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            payload = error_envelope(
                provider="youtube.retrieve",
                error_code="INVALID_YTDLP_JSON",
                error_message="Failed to parse yt-dlp JSON output.",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"url": input_url, "video_id": video_id or None})
            return payload

        resolved_video_id = str(meta.get("id") or video_id or "").strip() or None
        resolved_url = str(meta.get("webpage_url") or input_url)
        warnings: List[str] = []
        language = str(meta.get("language") or "").strip() or None

        transcript_value: Optional[str] = None
        transcript_available = False
        transcript_error_code: Optional[str] = None

        if include_transcript:
            caption_url, caption_lang = _pick_caption_url(meta)
            if caption_lang:
                language = language or caption_lang
            if caption_url:
                try:
                    with httpx.Client(timeout=httpx.Timeout(max(1.0, min(30.0, transcript_timeout_ms / 1000.0)))) as client:
                        caption_resp = client.get(caption_url)
                    if caption_resp.status_code < 400:
                        transcript_value = _truncate(_vtt_to_text(caption_resp.text), max_chars)
                        if transcript_value:
                            transcript_available = True
                        else:
                            transcript_error_code = "TRANSCRIPT_EMPTY"
                            warnings.append("Transcript fetched but empty after normalization.")
                    else:
                        transcript_error_code = "TRANSCRIPT_HTTP_ERROR"
                        warnings.append(f"Transcript HTTP error: {caption_resp.status_code}")
                except Exception as e:
                    transcript_error_code = "TRANSCRIPT_FETCH_FAILED"
                    warnings.append(f"Transcript fetch failed: {e}")
            else:
                transcript_error_code = "TRANSCRIPT_UNAVAILABLE"
                warnings.append("Automatic subtitles not available.")
        else:
            transcript_error_code = "TRANSCRIPT_NOT_REQUESTED"

        payload = success_envelope(
            provider="youtube.retrieve",
            elapsed=int((perf_counter() - started) * 1000),
            warnings=warnings,
        )
        payload.update(
            {
                "url": resolved_url,
                "video_id": resolved_video_id,
                "title": meta.get("title"),
                "channel": meta.get("channel") or meta.get("uploader"),
                "published_at": _parse_published(meta.get("upload_date")),
                "language": language,
                "description": _truncate(meta.get("description") or "", max_chars),
                "transcript": transcript_value,
                "transcript_available": transcript_available,
                "transcript_error_code": transcript_error_code,
            }
        )
        return payload
