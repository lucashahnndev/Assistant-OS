import os
import importlib
import inspect
import sys
from utils.logging_config import get_logger

logger = get_logger("PluginLoader")

class PluginLoader:
    @staticmethod
    def load_plugins(directory, base_class):
        """
        Scans a directory for python modules and returns classes that inherit from base_class.
        
        :param directory: Absolute path to the directory containing plugins.
        :param base_class: The class that plugins must inherit from.
        :return: A dictionary {module_name: class_reference}
        """
        plugins = {}
        
        if not os.path.exists(directory):
            logger.warning(f"Plugin directory not found: {directory}")
            return plugins

        # Ensure directory is in path so we can import modules
        if directory not in sys.path:
            sys.path.append(directory)

        # List all python files
        for filename in os.listdir(directory):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = filename[:-3]
                try:
                    # Construct valid package name if loading from a context
                    # e.g. services.tts.providers.google
                    package_parts = directory.split('src/')[-1].replace('/', '.')
                    full_module_name = f"{package_parts}.{module_name}"
                    
                    # Import the module
                    spec = importlib.util.spec_from_file_location(full_module_name, os.path.join(directory, filename))
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        # Set package context for relative imports inside plugin
                        module.__package__ = package_parts
                        sys.modules[full_module_name] = module
                        spec.loader.exec_module(module)
                        
                        # Find classes in the module
                        for name, obj in inspect.getmembers(module):
                            if inspect.isclass(obj) and issubclass(obj, base_class) and obj is not base_class:
                                plugins[module_name] = obj
                except Exception as e:
                    logger.error(f"Error loading plugin {filename}: {e}")
                    
        return plugins
