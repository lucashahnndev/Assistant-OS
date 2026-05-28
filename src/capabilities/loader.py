import os
import json
import importlib
from typing import Any, Dict

from .registry import CapabilityRegistry
from .contract_v1 import (
    CapabilityContractV1,
    load_contract_v1,
    load_contract_config_schema,
    resolve_contract_config_schema_path,
    validate_auth_schema_alignment,
    validate_auth_configuration,
)
from utils.schema_utils import validate_json_instance
import logging

logger = logging.getLogger("CapabilityLoader")


class CapabilityLoader:
    def __init__(self, registry: CapabilityRegistry, kernel: Any = None, config_manager: Any = None):
        self.registry = registry
        self._kernel = kernel
        self.config_manager = config_manager
        self.failed_contracts: Dict[str, str] = {}
        
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
        """Propagates the kernel reference to all currently registered capabilities."""
        logger.info(f"Propagating kernel to {len(self.registry.capabilities)} capabilities.")
        for capability in self.registry.capabilities.values():
            propagated = False
            if hasattr(capability, "kernel"):
                capability.kernel = kernel
                propagated = True
            elif hasattr(capability, "_kernel"):
                capability._kernel = kernel
                propagated = True
            
            if propagated:
                logger.info(f"Propagated kernel (id={id(kernel)}) to capability: {capability.name} (id={id(capability)})")
            else:
                logger.warning(f"Capability {capability.name} does not have 'kernel' or '_kernel' attribute.")

    def load_from_directory(self, directory: str) -> None:
        """Loads modular capabilities from a directory."""
        if not os.path.exists(directory):
            logger.warning(f"Capability directory {directory} does not exist.")
            return

        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            
            # Support only folder-based modules.
            if not os.path.isdir(path):
                continue
            if name.startswith("__") or name in {"shared", "index"}:
                continue
            self._load_from_folder(path)

    @staticmethod
    def _resolve_config(folder_name: str, config_manager: Any) -> Dict[str, Any]:
        if not config_manager:
            return {}
        raw_config: Dict[str, Any] = {}
        config_file = getattr(config_manager, "config_file", None)
        if config_file and os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as handle:
                    raw_config = json.load(handle) or {}
            except Exception:
                raw_config = {}
        capabilities_config = raw_config.get("capabilities", {}) or {}
        return dict(capabilities_config.get(folder_name, {}) or {})

    @staticmethod
    def _validate_config_schema(
        contract: CapabilityContractV1,
        contract_path: str,
        capability_config: Dict[str, Any],
        registry: CapabilityRegistry,
        capability_folder_name: str,
    ) -> None:
        schema_path = resolve_contract_config_schema_path(contract_path, contract)
        if not schema_path:
            auth_schema_errors = validate_auth_schema_alignment(contract=contract, schema=None)
            if auth_schema_errors:
                raise ValueError("; ".join(auth_schema_errors))
            return
        schema = load_contract_config_schema(contract_path, contract)
        if schema is None:
            raise ValueError("config schema not found")
        registry.schemas[capability_folder_name] = schema
        auth_schema_errors = validate_auth_schema_alignment(contract=contract, schema=schema)
        if auth_schema_errors:
            raise ValueError("; ".join(auth_schema_errors))
        if capability_config:
            validate_json_instance(instance=capability_config, schema=schema)
        auth_errors = validate_auth_configuration(
            contract=contract,
            config=capability_config,
            enabled=bool(capability_config.get("enabled", False)),
        )
        if auth_errors:
            raise ValueError("; ".join(auth_errors))

    @staticmethod
    def _assert_runtime_contract_alignment(capability_instance: Any, contract: CapabilityContractV1) -> None:
        namespace = contract.capability.namespace
        runtime_actions = set()
        for action in getattr(capability_instance, "actions", []) or []:
            action_id = str(action or "").strip()
            if not action_id:
                continue
            if action_id.startswith(f"{namespace}."):
                runtime_actions.add(action_id)
            else:
                runtime_actions.add(f"{namespace}.{action_id}")
        contract_actions = {action.id for action in contract.actions}
        if runtime_actions != contract_actions:
            raise ValueError(
                "runtime actions mismatch contract actions | "
                f"runtime={sorted(runtime_actions)} contract={sorted(contract_actions)}"
            )

    def _load_from_folder(self, folder_path: str) -> None:
        """Loads a modular capability from a folder."""
        capability_folder_name = os.path.basename(folder_path)
        try:
            contract_file = os.path.join(folder_path, "contract.json")
            if not os.path.exists(contract_file):
                raise ValueError("missing contract.json")

            contract = load_contract_v1(contract_file)

            capability_config = self._resolve_config(capability_folder_name, self.config_manager)
            if not capability_config.get("enabled", True):
                logger.info(f"Capability {capability_folder_name} is disabled via config.")
                return

            self._validate_config_schema(
                contract=contract,
                contract_path=contract_file,
                capability_config=capability_config,
                registry=self.registry,
                capability_folder_name=capability_folder_name,
            )

            module = importlib.import_module(contract.runtime.module)
            factory = getattr(module, contract.runtime.factory, None)
            if not callable(factory):
                raise ValueError(
                    f"runtime factory '{contract.runtime.factory}' not found in module '{contract.runtime.module}'"
                )

            capability_instance = factory(self.kernel, capability_config)
            self._assert_runtime_contract_alignment(capability_instance, contract)

            capability_instance._capability_contract = contract
            capability_instance._namespace = contract.capability.namespace
            self.registry.register(capability_instance, contract)
            logger.info(
                "Loaded modular capability: %s (Actions: %d)",
                capability_folder_name,
                len(contract.actions),
            )
            
            # Handle Auto-Start
            if capability_config.get("autostart", False):
                try:
                    action_id = f"{contract.capability.namespace}.start"
                    # Only auto-start if the capability actually has a 'start' action
                    if any(a.id == "start" or a.id == action_id for a in contract.actions):
                        logger.info(f"Auto-starting capability: {capability_folder_name}")
                        # Execute in background or synchronously (it usually returns immediately for tunnels)
                        capability_instance.execute(action_id, {}, {})
                except Exception as e:
                    logger.error(f"Auto-start failed for capability {capability_folder_name}: {e}")
                    
            self.failed_contracts.pop(capability_folder_name, None)
        except Exception as e:
            message = str(e)
            self.failed_contracts[capability_folder_name] = message
            logger.error("Failed to load capability '%s': %s", capability_folder_name, message)
