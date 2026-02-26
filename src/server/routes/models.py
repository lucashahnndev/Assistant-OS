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

def _read_env_file(path: str) -> dict:
    data = {}
    if not os.path.exists(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data

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

@router.get("/env-keys")
def get_env_keys(user: User = Depends(get_current_user)):
    """
    Returns a list of keys currently stored in the .env file that might be used as references.
    Does not expose values.
    """
    env_path = os.path.join(os.getcwd(), ".env")
    env_data = _read_env_file(env_path)
    return {"keys": [key for key in env_data.keys() if key.startswith("ENV_") or key.endswith("_KEY") or key.endswith("_TOKEN")]}

@router.post("/env-keys")
def create_env_key(payload: dict, user: User = Depends(get_current_user), request: Request = None):
    """
    Creates a new key in the .env file securely.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can modify environment")
        
    key = payload.get("key")
    value = payload.get("value")
    
    if not key or not value:
        raise HTTPException(status_code=400, detail="Key and value are required")
        
    env_path = os.path.join(os.getcwd(), ".env")
    env_data = _read_env_file(env_path)
    
    if key in env_data:
        raise HTTPException(status_code=409, detail="Key already exists in .env")
        
    mode = 'a' if os.path.exists(env_path) else 'w'
    with open(env_path, mode, encoding='utf-8') as f:
        f.write(f"\n{key}={value}\n")
        
    # Trigger hot-reload of config so env vars get picked up natively in process
    kernel = get_kernel(request)
    if kernel:
        import os as builtin_os
        builtin_os.environ[key] = value # Inject immediately
        kernel.reload_config()
        
    return {"success": True, "key": key}

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
            
        # Ensure api_key_ref starts with ENV_
        for item in pool:
            if "api_key_ref" in item and item["api_key_ref"]:
                if not item["api_key_ref"].startswith("ENV_"):
                    item["api_key_ref"] = f"ENV_{item['api_key_ref']}"
            
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
