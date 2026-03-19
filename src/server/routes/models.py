from fastapi import APIRouter, Depends, HTTPException, Request, Body
import os
import json
from ..auth import get_current_user
from ..core.models import User

router = APIRouter(prefix="/api/models", tags=["models"])

def get_kernel(request: Request):
    if not hasattr(request.app.state, "kernel") or not request.app.state.kernel:
        raise HTTPException(status_code=503, detail="Kernel not initialized")
    return request.app.state.kernel


def _load_provider_catalog(provider: str) -> dict:
    index_path = os.path.join(os.getcwd(), "src", "providers", provider, "index.json")
    if not os.path.exists(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

@router.get("/catalog")
def get_catalog(user: User = Depends(get_current_user)):
    """
    Returns a unified catalog array of all available model providers and their metadata.
    """
    base_dir = os.path.join(os.getcwd(), "src", "providers")
    catalog = {}
    if not os.path.exists(base_dir):
        return catalog
        
    for provider_name in os.listdir(base_dir):
        index_path = os.path.join(base_dir, provider_name, "index.json")
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    catalog[provider_name] = data
            except Exception as e:
                print(f"Failed to load catalog for {provider_name}: {e}")
                
    return catalog

@router.get("/catalog/{provider}")
def get_provider_catalog(provider: str, user: User = Depends(get_current_user)):
    """
    Returns the specific catalog for a given provider.
    """
    index_path = os.path.join(os.getcwd(), "src", "providers", provider, "index.json")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Provider catalog not found")
        
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to parse catalog JSON")

@router.post("/pool/{modality}")
def update_modality_pool(modality: str, pool: list = Body(...), user: User = Depends(get_current_user), request: Request = None):
    """
    Updates the model pool array for a given modality (chat, vision, stt, tts)
    and applies it without restarting the server.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can configure models")
        
    if modality not in ["chat", "vision", "stt", "tts"]:
        raise HTTPException(status_code=400, detail="Invalid modality")
        
    config_path = os.path.join(os.getcwd(), "data", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        if "cortex" not in config:
            config["cortex"] = {}
            
        for item in pool:
            provider_name = str(item.get("provider") or "").strip()
            provider_catalog = _load_provider_catalog(provider_name) if provider_name else {}
            auth_fields = provider_catalog.get("auth", {}).get("fields", [])
            settings_fields = provider_catalog.get("settings_fields", [])
            for field in [*auth_fields, *settings_fields]:
                if not isinstance(field, dict) or field.get("type") != "secret_ref":
                    continue
                field_key = str(field.get("key") or "").strip()
                if not field_key or not item.get(field_key):
                    continue
                if not str(item[field_key]).startswith("ENV_"):
                    item[field_key] = f"ENV_{item[field_key]}"
            
        if modality in ["chat", "vision"]:
            config["cortex"][modality] = pool
        else:
            if "audio" not in config["cortex"]:
                config["cortex"]["audio"] = {}
            config["cortex"]["audio"][modality] = pool
            
        with open(config_path, "w", encoding="utf-8") as fw:
            json.dump(config, fw, indent=4)
            
        # Hot-reload the LLM/TTS Manager
        kernel = get_kernel(request)
        if hasattr(kernel, 'config_manager'):
            kernel.config_manager.load() # Read the fresh config
            
        if modality in ["chat", "vision"]:
            if hasattr(kernel, 'llm_manager'):
                kernel.llm_manager.reload()
                
        elif modality in ["stt", "tts"]:
            # Need to reload audio manager if it handles reload
            if hasattr(kernel, 'tts_manager'):
                pass # tts_manager loads dynamically in some versions, or needs a reload()
                
        return {"success": True, "pool": pool}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update model pool: {str(e)}")
