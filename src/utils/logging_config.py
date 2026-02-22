import logging
import logging.handlers
import os
import sys

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

    # Root Logger initialization
    root_logger = logging.getLogger()
    root_logger.setLevel(global_level)
    
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
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

    # Silence noise from specific libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    
    logging.info(f"Logging initialized. Mode: {'Separated' if separate_files else 'Unified'}")

def _setup_service_logs(log_dir, formatter, service_levels):
    """Configures specific loggers to output to their own files."""
    
    mapping = {
        "llm": ["LLMManager", "AgentOrchestrator", "LLMResolver", "SemanticResolver", "LLMService"],
        "telegram": ["TelegramDriver", "drivers.telegram.telegram_bot", "TelegramBot"],
        "web": ["ServerDriver"],
        "api": ["PortalServer", "SystemRoutes", "AuthRoutes", "SkillRoutes", "MemoryRoutes", "SessionRoutes", "TaskRoutes"],
        "skills": ["SkillLoader", "SkillRegistry"],
        "interface": ["VoiceDriver", "BrowserDriver", "SystemDriver", "Kernel"]
    }

    # Add individual skill loggers to the skills category
    # We can use a special logic for loggers ending with "Skill" if needed, 
    # but for now we'll stick to the explicit mapping and handle dynamic discovery later.

    for service, logger_names in mapping.items():
        file_path = os.path.join(log_dir, f"{service}.log")
        handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        handler.setFormatter(formatter)
        
        # Level for this service
        level_str = service_levels.get(service, "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

        for name in logger_names:
            logger = logging.getLogger(name)
            logger.addHandler(handler)
            logger.setLevel(level)
            # Ensure it doesn't propagate the individual handler's logs to root twice 
            # (Wait, actually if we add a handler to a child, it logs there. 
            # If propagate is true it also logs to root's handlers. 
            # This is exactly what we want: specific file + assistant.log.)

    # Special case: All loggers containing "Skill" in their name go to skills.log
    # This is hard to do globally without intercepting logger creation, 
    # but we can pre-configure common ones.
    common_skills = ["SystemSkill", "SearchSkill", "MemorySkill", "PowerSkill", "ReflexSkill", 
                     "ShellSkill", "MediaSkill", "ServiceSkill", "SystemAppsSkill", "SystemLogsSkill",
                     "FSSkill", "TaskSkill", "NetworkSkill", "ProcessSkill"]
    
    skills_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "skills.log"), maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
    )
    skills_handler.setFormatter(formatter)
    skills_level = getattr(logging, service_levels.get("skills", "INFO").upper(), logging.INFO)

    for skill_name in common_skills:
        logger = logging.getLogger(skill_name)
        logger.addHandler(skills_handler)
        logger.setLevel(skills_level)

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
