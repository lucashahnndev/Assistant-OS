import logging
import logging.handlers
import os
import sys

class AnsiColorFormatter(logging.Formatter):
    """
    Applies ANSI colors for console output only.
    File handlers should keep plain text formatting.
    """
    RESET = "\033[0m"
    COLORS = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[1;31m" # Bold Red
    }

    def format(self, record):
        base = super().format(record)
        color = self.COLORS.get(record.levelno, "")
        if not color:
            return base
        return f"{color}{base}{self.RESET}"


def setup_logging():
    """
    Configures the root logger and service-specific loggers.
    """
    import json
    
    # Path Resolution
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(root_dir, 'data', 'logs')
    config_path = os.path.join(root_dir, 'data', 'config.json')
    os.makedirs(log_dir, exist_ok=True)
    
    # Load Config
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f).get("logging", {})
        except Exception:
            pass
            
    global_level_str = config.get("level", "INFO").upper()
    global_level = getattr(logging, global_level_str, logging.INFO)
    separate_files = config.get("separate_files", True)
    service_levels = config.get("services", {})

    # Define Formatting
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    enable_console_colors = bool(config.get("console_colors", True))
    no_color_env = bool(os.getenv("NO_COLOR"))
    supports_tty_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    use_color_formatter = enable_console_colors and supports_tty_color and not no_color_env
    console_formatter = AnsiColorFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ) if use_color_formatter else formatter

    # Root Logger initialization
    root_logger = logging.getLogger()
    root_logger.setLevel(global_level)
    
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Main Assistant Log (Unified)
    log_path = os.path.join(log_dir, "assistant.log")
    main_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    main_handler.setFormatter(formatter)
    root_logger.addHandler(main_handler)

    if separate_files:
        _setup_service_logs(log_dir, formatter, service_levels)
        _cleanup_legacy_logs(log_dir)

    # Silence noise from specific libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    
    logging.info(f"Logging initialized. Mode: {'Separated' if separate_files else 'Unified'}")

def _setup_service_logs(log_dir, formatter, service_levels):
    """Configures specific loggers to output to their own files."""
    
    mapping = {
        "llm": ["LLMManager", "AgentOrchestrator", "LLMResolver", "LLMService"],
        "telegram": ["TelegramDriver", "drivers.interfaces.telegram.telegram_bot", "TelegramBot"],
        "web": ["ServerDriver"],
        "api": ["PortalServer", "SystemRoutes", "AuthRoutes", "CapabilityRoutes", "MemoryRoutes", "SessionRoutes", "TaskRoutes"],
        "capabilities": ["CapabilityLoader", "CapabilityRegistry"],
        "interface": ["VoiceDriver", "BrowserDriver", "SystemDriver", "Kernel"],
        "browser_control": [
            "aosd.capabilities.browser_control",
            "aosd.capabilities.browser_control.planner",
            "aosd.capabilities.browser_control.dom_analyzer",
            "aosd.capabilities.browser_control.image_analyzer",
            "aosd.capabilities.browser_control.perception_merger",
            "aosd.capabilities.browser_control.runtime"
        ],
        "browser_cdp": [
            "aosd.capabilities.browser_control.cdp"
        ],
        "browser_extension": [
            "aosd.capabilities.browser_control.extension",
            "aosd.capabilities.browser_control.runtime.extension"
        ],
        "browser_events": [
            "aosd.capabilities.browser_control.events",
            "aosd.capabilities.browser_control.runtime.events"
        ]
    }

    # Add individual capability loggers to the capabilities category
    # We can use a special logic for loggers ending with "Capability" if needed, 
    # but for now we'll stick to the explicit mapping and handle dynamic discovery later.

    def _has_managed_ancestor(name, names):
        parts = name.split(".")
        for i in range(1, len(parts)):
            ancestor = ".".join(parts[:i])
            if ancestor in names:
                return True
        return False

    def _clear_existing_service_handlers(logger_obj):
        retained = []
        for h in logger_obj.handlers:
            base = getattr(h, "baseFilename", "")
            if isinstance(h, logging.handlers.RotatingFileHandler) and str(base).startswith(log_dir):
                continue
            retained.append(h)
        logger_obj.handlers = retained

    for service, logger_names in mapping.items():
        file_path = os.path.join(log_dir, f"{service}.log")
        handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        handler.setFormatter(formatter)
        
        # Level for this service
        level_str = service_levels.get(service, "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

        names_set = set(logger_names)
        attach_names = [name for name in logger_names if not _has_managed_ancestor(name, names_set)]

        for name in attach_names:
            logger = logging.getLogger(name)
            _clear_existing_service_handlers(logger)
            logger.addHandler(handler)
            logger.setLevel(level)
            # Ensure it doesn't propagate the individual handler's logs to root twice 
            # (Wait, actually if we add a handler to a child, it logs there. 
            # If propagate is true it also logs to root's handlers. 
            # This is exactly what we want: specific file + assistant.log.)

    # Special case: All loggers containing "Capability" in their name go to capabilities.log
    # This is hard to do globally without intercepting logger creation, 
    # but we can pre-configure common ones.
    common_capabilities = ["SystemCapability", "SearchCapability", "MemoryCapability", "PowerCapability", "ReflexCapability", 
                     "ShellCapability", "MediaCapability", "ServiceCapability", "SystemAppsCapability", "SystemLogsCapability",
                     "FSCapability", "TaskCapability", "NetworkCapability", "ProcessCapability"]
    
    capabilities_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "capabilities.log"), maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
    )
    capabilities_handler.setFormatter(formatter)
    capabilities_level = getattr(logging, service_levels.get("capabilities", "INFO").upper(), logging.INFO)

    for capability_name in common_capabilities:
        logger = logging.getLogger(capability_name)
        logger.addHandler(capabilities_handler)
        logger.setLevel(capabilities_level)


def _cleanup_legacy_logs(log_dir):
    """
    Removes deprecated browser_automation log files after migrating to
    browser_control/browser_cdp/browser_extension/browser_events logs.
    """
    legacy_prefixes = ("browser_automation.log",)
    try:
        for entry in os.listdir(log_dir):
            if any(entry.startswith(prefix) for prefix in legacy_prefixes):
                legacy_path = os.path.join(log_dir, entry)
                try:
                    os.remove(legacy_path)
                except Exception:
                    # Ignore cleanup failures to avoid blocking startup.
                    pass
    except Exception:
        pass

def get_logger(name):
    """Returns a logger with the specified name."""
    return logging.getLogger(name)

def list_log_files():
    """Returns a list of all available log files in data/logs."""
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir = os.path.join(root_dir, 'data', 'logs')
    if not os.path.exists(log_dir):
        return []
    return sorted([f for f in os.listdir(log_dir) if f.endswith(".log")])

def read_recent_logs(n=20, filename="assistant.log"):
    """
    Reads the last n lines from a specific log file in data/logs.
    """
    try:
        # Security: Prevent path traversal by only allowing filenames without directory components
        filename = os.path.basename(filename)
        if not filename.endswith(".log"):
            return [f"Error: Invalid log file type '{filename}'."]

        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        log_dir = os.path.join(root_dir, 'data', 'logs')
        log_path = os.path.join(log_dir, filename)
        
        if not os.path.exists(log_path):
            return [f"Log file '{filename}' not found."]
        
        with open(log_path, 'rb') as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size == 0:
                    return [f"Log file '{filename}' is empty."]
                
                # Simple read-back for small n
                f.seek(0)
                lines = f.readlines()
                decoded_lines = [line.decode('utf-8', errors='ignore').strip() for line in lines]
                return decoded_lines[-n:]
            except OSError:
                f.seek(0)
                lines = f.readlines()
                decoded_lines = [line.decode('utf-8', errors='ignore').strip() for line in lines]
                return decoded_lines[-n:]
            
    except Exception as e:
        return [f"Error reading {filename}: {str(e)}"]
