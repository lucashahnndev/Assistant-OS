from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.database import init_db
from .routes import auth, system, skills, memory, sessions, tasks, messaging_access, link_preview, models, external_accounts
from utils.event_bus import global_event_bus
import logging
import asyncio
import os

# Configure logging for uvicorn 
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PortalServer")

def _resolve_cors_config(kernel):
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ]

    configured = []
    if kernel and hasattr(kernel, "config_manager"):
        server_cfg = kernel.config_manager.get_interfaces_config().get("server", {})
        configured = server_cfg.get("cors_origins", []) or []

    if isinstance(configured, str):
        configured = [v.strip() for v in configured.split(",")]

    origins = [v.strip() for v in configured if isinstance(v, str) and v.strip()]
    if not origins:
        env_origins = os.getenv("AOSD_CORS_ORIGINS", "").strip()
        if env_origins:
            origins = [v.strip() for v in env_origins.split(",") if v.strip()]

    if not origins:
        origins = default_origins

    allow_credentials = "*" not in origins
    if not allow_credentials:
        logger.warning("CORS origins contain '*'. Disabling allow_credentials for safety/compliance.")

    return origins, allow_credentials

def create_app(kernel=None) -> FastAPI:
    """
    Creates and configures the FastAPI application.
    Kernel is injected into app.state for access by routes.
    """
    # Initialize Database
    init_db()
    
    app = FastAPI(title="AOSD Portal", version="1.0.0")
    app.state.kernel = kernel
    
    # CORS Configuration
    cors_origins, allow_credentials = _resolve_cors_config(kernel)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include Routers (Prefixes are defined within each router module)
    app.include_router(auth.router, tags=["auth"])
    app.include_router(system.router, tags=["system"])
    app.include_router(skills.router, tags=["skills"])
    app.include_router(memory.router, tags=["memory"])
    app.include_router(sessions.router, tags=["sessions"])
    app.include_router(tasks.router, tags=["tasks"])
    app.include_router(messaging_access.router, tags=["access"])
    app.include_router(link_preview.router, tags=["link_preview"])
    app.include_router(models.router, tags=["models"])
    app.include_router(external_accounts.router, tags=["external_accounts"])

    from fastapi.staticfiles import StaticFiles
    import os
    
    # Static files (attachments, etc.)
    base_data_dir = kernel.config_manager.get_data_dir() if (kernel and hasattr(kernel.config_manager, 'get_data_dir')) else os.path.join(os.getcwd(), "data")
    static_dir = os.path.join(base_data_dir, "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/api/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def read_root():
        return {"app": "AOSD Portal", "status": "running"}

    return app
