import os
import json
import importlib.util
from typing import List, Optional, Any
from .base import SkillBase
from .registry import SkillRegistry
import logging

try:
    import jsonschema
except ImportError:
    jsonschema = None

logger = logging.getLogger("SkillLoader")

class SkillLoader:
    def __init__(self, registry: SkillRegistry, kernel: Any = None, config_manager: Any = None):
        self.registry = registry
        self._kernel = kernel
        self.config_manager = config_manager
        
        if kernel:
            self._propagate_kernel(kernel)

    @property
    def kernel(self):
        return self._kernel

    @kernel.setter
    def kernel(self, value):
        self._kernel = value
        if value:
            self._propagate_kernel(value)

    def _propagate_kernel(self, kernel):
        """Propagates the kernel reference to all currently registered skills."""
        logger.info(f"Propagating kernel to {len(self.registry.skills)} skills.")
        for skill in self.registry.skills.values():
            if hasattr(skill, "kernel"):
                skill.kernel = kernel
                logger.info(f"Propagated kernel (id={id(kernel)}) to skill: {skill.name} (id={id(skill)})")
            else:
                logger.warning(f"Skill {skill.name} does not have 'kernel' attribute.")

    def load_from_directory(self, directory: str):
        """Loads modular skills from a directory."""
        if not os.path.exists(directory):
            logger.warning(f"Skill directory {directory} does not exist.")
            return

        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            
            # support only Folder-based Skills
            if os.path.isdir(path):
                if name.startswith("__") or name == "shared": continue
                self._load_from_folder(path)

    def _load_from_folder(self, folder_path: str):
        """Loads a modular skill from a folder."""
        try:
            skill_folder_name = os.path.basename(folder_path)
            init_file = os.path.join(folder_path, "__init__.py")
            contract_file = os.path.join(folder_path, "contract.json")
            schema_file = os.path.join(folder_path, "config.schema.json")
            
            if not os.path.exists(init_file):
                logger.debug(f"Skipping folder {folder_path}: No __init__.py")
                return

            # Load module
            module_name = f"skills.{skill_folder_name}"
            spec = importlib.util.spec_from_file_location(module_name, init_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Check for create_skill contract
            if hasattr(module, "create_skill"):
                # Load per-skill config from global config
                skill_config = {}
                if self.config_manager:
                    skills_config = self.config_manager.get("skills", {})
                    # Try both folder name and possible namespace name
                    skill_config = skills_config.get(skill_folder_name, {})
                
                # Check if enabled
                if not skill_config.get("enabled", True):
                    logger.info(f"Skill {skill_folder_name} is disabled via config.")
                    return

                # Load contract for metadata/namespacing
                contract = {}
                if os.path.exists(contract_file):
                    with open(contract_file, 'r') as f:
                        contract = json.load(f)

                # Validate config if schema exists
                schema = {}
                if os.path.exists(schema_file):
                    try:
                        with open(schema_file, 'r') as f:
                            schema = json.load(f)
                        self.registry.schemas[skill_folder_name] = schema
                        
                        if jsonschema and skill_config:
                            jsonschema.validate(instance=skill_config, schema=schema)
                    except jsonschema.exceptions.ValidationError as ve:
                        logger.error(f"Config validation failed for {skill_folder_name}: {ve.message}")
                    except Exception as e:
                        logger.error(f"Error validating schema for {skill_folder_name}: {e}")

                skill_instance = module.create_skill(self.kernel, skill_config)
                
                # Assign contract if it exists 
                if contract:
                    skill_instance._contract = contract
                    
                    # Store namespace for registration
                    namespace = contract.get("name", skill_folder_name).lower().replace(" ", ".")
                    skill_instance._namespace = namespace

                self.registry.register(skill_instance)
                logger.info(f"Loaded modular skill: {skill_folder_name} (Actions: {len(skill_instance.actions)})")
            else:
                logger.debug(f"Skipping folder {folder_path}: No create_skill found in __init__.py")
                
        except Exception as e:
            logger.error(f"Failed to load skill from folder {folder_path}: {e}")
