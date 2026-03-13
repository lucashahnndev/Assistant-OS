from typing import TypedDict, List, Optional, Dict, Any
from pydantic import BaseModel, Field

class DriverCapabilities(TypedDict):
    """
    Defines what an interface driver can and cannot do.
    Used by the Kernel to adapt cognitive strategies without knowing the driver name.
    """
    supports_markdown: bool
    supports_rich_media: bool  # Images, Videos
    is_voice_only: bool        # True for Alexa/Siri-like interfaces
    supports_streaming: bool   # Can handle partial text chunks
    preferred_language: str    # e.g., "pt-BR"
    input_type: str           # "text", "voice", "event"

class UniversalInputFrame(BaseModel):
    """
    A canonical input format from any interface driver to the Kernel.
    """
    text: str = Field(..., description="The raw or transcribed text input")
    user_id: str = Field(..., description="Unique platform identifier for the user")
    session_id: str = Field(..., description="Unique session identifier")
    interface: str = Field(..., description="The name of the interface (e.g., 'telegram', 'web')")
    capabilities: DriverCapabilities
    media_paths: List[str] = Field(default_factory=list, description="Paths to attached files or images")
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="Platform-specific metadata")
