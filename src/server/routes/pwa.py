"""
Dynamic PWA Manifest route.

Generates the Web App Manifest at request time, resolving start_url and scope
from the actual request URL. This means the PWA installs correctly whether the
user is on localhost, a Cloudflare tunnel, or any ephemeral ngrok URL.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os
import json
import logging

router = APIRouter()
logger = logging.getLogger("PWAManifest")

AGENT_CONFIG_PATH = os.path.join(os.getcwd(), "data", "config.json")


def _load_agent_name() -> str:
    """Read agent name from config.json without importing the full kernel."""
    try:
        with open(AGENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("agent", {}).get("agent_name") or cfg.get("agent", {}).get("spoken_name") or "Assistant"
    except Exception as e:
        logger.warning("Could not read agent name from config: %s", e)
        return "Assistant"


@router.get("/api/manifest.webmanifest", include_in_schema=False)
async def get_pwa_manifest(request: Request):
    """
    Returns a PWA Web App Manifest.
    Uses relative paths so it works seamlessly across localhost, ngrok, and Cloudflare tunnels.
    """
    agent_name = _load_agent_name()

    # Try kernel for a fresher value (available after startup)
    try:
        kernel = getattr(request.app.state, "kernel", None)
        if kernel and hasattr(kernel, "config_manager"):
            agent_cfg = kernel.config_manager.get_agent_config()
            agent_name = agent_cfg.get("agent_name") or agent_name
    except Exception:
        pass

    manifest = {
        "name": agent_name,
        "short_name": agent_name,
        "description": f"{agent_name} — Intelligent Assistant OS",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#030406",
        "theme_color": "#030406",
        "icons": [
            {
                "src": "/api/static/logo-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/api/static/logo-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ],
        "categories": ["productivity", "utilities"],
        "lang": "pt-BR"
    }

    return JSONResponse(
        content=manifest,
        headers={
            "Content-Type": "application/manifest+json",
            # Must NOT be cached — needs to reflect the current tunnel URL
            "Cache-Control": "no-cache, no-store, must-revalidate",
        }
    )
