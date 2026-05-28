import os
import json
import logging
from typing import Optional, Dict, List, Any
import fnmatch
from .identity import (
    PrincipalContext,
    UserEntity,
    ChatEntity,
    PermissionGroup,
    AccessStatus,
    AccessMode,
    RiskLevel,
)

logger = logging.getLogger("AccessController")

class IdentityService:
    INTERFACE_ALIASES = {
        "validator": "cli",
        "terminal_bridge": "cli",
    }

    def __init__(self, data_dir: str):
        self.identities_dir = os.path.join(data_dir, "identities")
        self.users_dir = os.path.join(self.identities_dir, "users")
        self.chats_dir = os.path.join(self.identities_dir, "chats")
        self.config_file = os.path.join(self.identities_dir, "policy.json")
        
        os.makedirs(self.users_dir, exist_ok=True)
        os.makedirs(self.chats_dir, exist_ok=True)
        
        self.policy = self._load_policy()

    def normalize_interface_name(self, interface: Optional[str]) -> str:
        raw = (interface or "").strip().lower()
        if not raw:
            return raw
        return self.INTERFACE_ALIASES.get(raw, raw)

    def _load_policy(self) -> Dict[str, Any]:
        policy = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    policy = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to parse policy.json, using defaults: {e}")
        if not policy:
            policy = self._default_policy()
        self._ensure_policy_shape(policy)
        return policy

    def _default_permission_groups(self) -> Dict[str, Dict[str, Any]]:
        return {
            "master": PermissionGroup(
                id="master",
                name="Master",
                description="Acesso total. Novas capabilities entram automaticamente via wildcard.",
                allow_actions=["*"],
                worker_view_scope="global",
                worker_control_scope="global",
                is_system=True,
            ).model_dump(),
            "medium": PermissionGroup(
                id="medium",
                name="Medium",
                description="Uso geral sem ações críticas de sistema.",
                allow_actions=[
                    "web.*",
                    "wikipedia.*",
                    "memory.*",
                    "task.*",
                    "weather.*",
                    "maps.*",
                    "youtube.*",
                    "deezer.*",
                    "spotify.*",
                    "vision.*",
                    "overlay.assist.*",
                    "system.logs.*",
                    "system.apps.*",
                    "system.control.info",
                    "system.control.time",
                    "system.control.status",
                    "system.control.network.*",
                    "system.control.process.list",
                    "system.control.screenshot",
                    "reflex.*",
                ],
                deny_actions=[
                    "shell.*",
                    "system.control.power",
                    "system.control.process.kill",
                    "system.control.fs.write",
                    "system.control.fs.delete",
                    "system.control.service.manage",
                ],
                worker_view_scope="owner_identity",
                worker_control_scope="owner_identity",
                is_system=True,
            ).model_dump(),
            "critical": PermissionGroup(
                id="critical",
                name="Critical",
                description="Somente observabilidade e ações de baixo risco.",
                allow_actions=[
                    "web.search.discover",
                    "web.retrieve.read",
                    "web.retrieve.extract",
                    "wikipedia.search",
                    "memory.recall",
                    "task.notes",
                    "task.specialist",
                    "weather.control.get",
                    "weather.control.forecast",
                    "maps.search.search",
                    "youtube.search.find",
                    "youtube.retrieve.get",
                    "research.retrieve.run",
                    "deezer.search.search",
                    "system.logs.*",
                    "system.control.info",
                    "system.control.time",
                    "system.control.status",
                    "system.control.network.status",
                    "system.control.network.ping",
                    "system.control.process.list",
                    "system.control.screenshot",
                    "vision.analyze",
                    "vision.search_screen",
                    "overlay.assist.*",
                    "reflex.*",
                ],
                deny_actions=["shell.*", "system.control.*"],
                worker_view_scope="self_session",
                worker_control_scope="self_session",
                is_system=True,
            ).model_dump(),
        }

    def _default_policy(self) -> Dict[str, Any]:
        return {
            "interfaces": {
                "telegram": {
                    "dm_mode": "auto_approve",
                    "group_mode": "approved_only",
                    "default_user_group": "medium",
                    "default_chat_group": "medium",
                    "auto_approve_user_group": "medium",
                    "auto_approve_chat_group": "medium",
                    "allow_anyone_in_chats": [],
                    "rate_limit_enabled": True,
                    "max_msgs_per_min": 20,
                    "approval_decisions": {
                        "enabled": True,
                        "allowed_groups": ["master"],
                        "denied_groups": [],
                    },
                },
                "web": {
                    "dm_mode": "anyone",
                    "group_mode": "anyone",
                    "default_user_group": "master",
                    "default_chat_group": "master",
                    "auto_approve_user_group": "master",
                    "auto_approve_chat_group": "master",
                    "allow_anyone_in_chats": [],
                    "rate_limit_enabled": False,
                    "max_msgs_per_min": 60,
                    "approval_decisions": {
                        "enabled": True,
                        "allowed_groups": ["*"],
                        "denied_groups": [],
                    },
                },
                "cli": {
                    "dm_mode": "anyone",
                    "group_mode": "anyone",
                    "default_user_group": "master",
                    "default_chat_group": "master",
                    "auto_approve_user_group": "master",
                    "auto_approve_chat_group": "master",
                    "allow_anyone_in_chats": [],
                    "rate_limit_enabled": False,
                    "max_msgs_per_min": 100,
                    "approval_decisions": {
                        "enabled": True,
                        "allowed_groups": ["master"],
                        "denied_groups": [],
                    },
                }
            },
            "permission_groups": self._default_permission_groups(),
            "global_admin_ids": []
        }

    def _ensure_policy_shape(self, policy: Dict[str, Any]):
        defaults = self._default_policy()

        if "interfaces" not in policy or not isinstance(policy["interfaces"], dict):
            policy["interfaces"] = defaults["interfaces"]

        interfaces = policy["interfaces"]
        # Legacy migration: validator/terminal_bridge were renamed to cli.
        legacy_entries = []
        for legacy_name in ("validator", "terminal_bridge"):
            data = interfaces.get(legacy_name)
            if isinstance(data, dict):
                legacy_entries.append(data)
        if "cli" not in interfaces:
            base_cli = dict(defaults["interfaces"]["cli"])
            for legacy in legacy_entries:
                base_cli.update(legacy)
            interfaces["cli"] = base_cli
        elif isinstance(interfaces.get("cli"), dict):
            for legacy in legacy_entries:
                for key, value in legacy.items():
                    interfaces["cli"].setdefault(key, value)
        interfaces.pop("validator", None)
        interfaces.pop("terminal_bridge", None)

        for interface_name, interface_defaults in defaults["interfaces"].items():
            current = policy["interfaces"].setdefault(interface_name, {})
            for key, value in interface_defaults.items():
                current.setdefault(key, value)
            current_approval = current.get("approval_decisions")
            default_approval = interface_defaults.get("approval_decisions", {})
            if not isinstance(current_approval, dict):
                current_approval = {}
                current["approval_decisions"] = current_approval
            for key, value in default_approval.items():
                current_approval.setdefault(key, value)

        if "permission_groups" not in policy or not isinstance(policy["permission_groups"], dict):
            policy["permission_groups"] = {}

        default_groups = self._default_permission_groups()
        for gid, group_data in default_groups.items():
            existing = policy["permission_groups"].get(gid, {})
            merged = dict(group_data)
            if isinstance(existing, dict):
                merged.update(existing)
            group_obj = PermissionGroup(**merged)
            policy["permission_groups"][gid] = group_obj.model_dump()

        policy.setdefault("global_admin_ids", [])

    def save_policy(self):
        with open(self.config_file, "w") as f:
            json.dump(self.policy, f, indent=4)

    def get_interface_config(self, interface: str) -> Dict[str, Any]:
        interface_name = self.normalize_interface_name(interface)
        return self.policy.get("interfaces", {}).get(interface_name, {
            "dm_mode": "approved_only",
            "group_mode": "approved_only",
            "default_user_group": "medium",
            "default_chat_group": "medium",
            "auto_approve_user_group": "medium",
            "auto_approve_chat_group": "medium",
            "allow_anyone_in_chats": [],
            "rate_limit_enabled": True,
            "max_msgs_per_min": 10,
            "approval_decisions": {
                "enabled": True,
                "allowed_groups": ["master"],
                "denied_groups": [],
            },
        })

    def list_permission_groups(self) -> List[Dict[str, Any]]:
        groups = self.policy.get("permission_groups", {})
        return [dict(value) for _, value in sorted(groups.items(), key=lambda x: x[0])]

    def resolve_permission_group_id(self, token: Optional[str]) -> str:
        """
        Resolve a group token to a canonical group id.
        Accepts exact id, case-insensitive id, display name, or slug-like variants.
        Returns empty string when unresolved.
        """
        raw = str(token or "").strip()
        if not raw:
            return ""

        groups = self.policy.get("permission_groups", {})
        if not isinstance(groups, dict) or not groups:
            return ""

        exact = raw.lower()
        if exact in groups:
            return exact

        compact = exact.replace(" ", "_")
        if compact in groups:
            return compact

        for gid, data in groups.items():
            if str(gid or "").strip().lower() == exact:
                return str(gid).strip().lower()
            name = ""
            if isinstance(data, dict):
                name = str(data.get("name") or "").strip().lower()
            if name and name in {exact, compact}:
                return str(gid).strip().lower()
            if name and name.replace(" ", "_") == compact:
                return str(gid).strip().lower()
        return ""

    def get_permission_group(self, group_id: str) -> Optional[PermissionGroup]:
        canonical_group_id = self.resolve_permission_group_id(group_id)
        if not canonical_group_id:
            return None
        group_data = self.policy.get("permission_groups", {}).get(canonical_group_id)
        if not group_data:
            return None
        try:
            return PermissionGroup(**group_data)
        except Exception as e:
            logger.warning(f"Invalid permission group '{canonical_group_id}': {e}")
            return None

    def save_permission_group(self, group: PermissionGroup):
        self.policy.setdefault("permission_groups", {})[group.id] = group.model_dump()
        self.save_policy()

    def delete_permission_group(self, group_id: str) -> bool:
        group = self.get_permission_group(group_id)
        if not group:
            return False
        if group.is_system and group.id == "master":
            raise ValueError("Group 'master' cannot be deleted.")

        # Avoid dangling references by re-pointing to a safe default.
        fallback_group = "master"
        for entity in self.list_entities("users"):
            if entity.get("group_id") == group_id:
                user = self.get_user(entity.get("interface"), entity.get("id"))
                if user:
                    user.group_id = fallback_group
                    self.save_user(user)
        for entity in self.list_entities("chats"):
            if entity.get("group_id") == group_id:
                chat = self.get_chat(entity.get("interface"), entity.get("id"))
                if chat:
                    chat.group_id = fallback_group
                    self.save_chat(chat)

        del self.policy["permission_groups"][group_id]
        self.save_policy()
        return True

    def _resolve_default_group(
        self,
        *,
        interface: str,
        mode: str,
        entity_type: str,
    ) -> str:
        conf = self.get_interface_config(interface)
        interface_lower = interface.lower()
        if entity_type == "chat":
            default_key = "default_chat_group"
            auto_key = "auto_approve_chat_group"
        else:
            default_key = "default_user_group"
            auto_key = "auto_approve_user_group"

        # Web portal main user should be master by default.
        if interface_lower == "web":
            return conf.get(auto_key) or conf.get(default_key) or "master"

        if mode in ("auto_approve", "anyone"):
            return conf.get(auto_key) or conf.get(default_key) or "medium"
        return conf.get(default_key) or "medium"

    def _ensure_valid_group(self, group_id: Optional[str], fallback: str) -> str:
        groups = self.policy.get("permission_groups", {})
        resolved = self.resolve_permission_group_id(group_id)
        if resolved and resolved in groups:
            return resolved
        return fallback if fallback in groups else "master"

    def ensure_user_group(self, user: UserEntity, interface: str, mode: Optional[str] = None) -> UserEntity:
        conf = self.get_interface_config(interface)
        dm_mode = mode or conf.get("dm_mode", "approved_only")
        fallback = self._resolve_default_group(interface=interface, mode=dm_mode, entity_type="user")
        target_group = self._ensure_valid_group(user.group_id, fallback)
        if user.group_id != target_group:
            user.group_id = target_group
            self.save_user(user)
        return user

    def ensure_chat_group(self, chat: ChatEntity, interface: str, mode: Optional[str] = None) -> ChatEntity:
        conf = self.get_interface_config(interface)
        group_mode = mode or conf.get("group_mode", "approved_only")
        fallback = self._resolve_default_group(interface=interface, mode=group_mode, entity_type="chat")
        target_group = self._ensure_valid_group(chat.group_id, fallback)
        if chat.group_id != target_group:
            chat.group_id = target_group
            self.save_chat(chat)
        return chat

    def get_user(self, interface: str, sender_id: str) -> Optional[UserEntity]:
        interface_name = self.normalize_interface_name(interface)
        path = os.path.join(self.users_dir, f"{interface_name}_{sender_id}.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return UserEntity(**json.load(f))
        legacy_name = (interface or "").lower()
        if legacy_name and legacy_name != interface_name:
            legacy_path = os.path.join(self.users_dir, f"{legacy_name}_{sender_id}.json")
            if os.path.exists(legacy_path):
                with open(legacy_path, "r") as f:
                    return UserEntity(**json.load(f))
        return None

    def create_user(self, context: PrincipalContext) -> UserEntity:
        interface_name = self.normalize_interface_name(context.interface)
        conf = self.get_interface_config(interface_name)
        mode = conf.get("dm_mode", "approved_only")
        
        status = AccessStatus.PENDING
        if mode == "auto_approve" or mode == "anyone":
            status = AccessStatus.APPROVED

        default_group = self._resolve_default_group(
            interface=interface_name,
            mode=mode,
            entity_type="user",
        )
        group_id = self._ensure_valid_group(default_group, "master")
            
        user = UserEntity(
            id=context.sender_id,
            interface=interface_name,
            display_name=context.sender_name,
            status=status,
            group_id=group_id,
        )
        self.save_user(user)
        return user

    def save_user(self, user: UserEntity):
        user.interface = self.normalize_interface_name(user.interface)
        path = os.path.join(self.users_dir, f"{user.interface}_{user.id}.json")
        with open(path, "w") as f:
            f.write(user.model_dump_json(indent=4))

    def get_chat(self, interface: str, chat_id: str) -> Optional[ChatEntity]:
        interface_name = self.normalize_interface_name(interface)
        path = os.path.join(self.chats_dir, f"{interface_name}_{chat_id}.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return ChatEntity(**json.load(f))
        legacy_name = (interface or "").lower()
        if legacy_name and legacy_name != interface_name:
            legacy_path = os.path.join(self.chats_dir, f"{legacy_name}_{chat_id}.json")
            if os.path.exists(legacy_path):
                with open(legacy_path, "r") as f:
                    return ChatEntity(**json.load(f))
        return None

    def create_chat(self, context: PrincipalContext) -> ChatEntity:
        interface_name = self.normalize_interface_name(context.interface)
        conf = self.get_interface_config(interface_name)
        mode = conf.get("group_mode", "approved_only")
        
        status = AccessStatus.PENDING
        if mode == "auto_approve" or mode == "anyone":
            status = AccessStatus.APPROVED

        default_group = self._resolve_default_group(
            interface=interface_name,
            mode=mode,
            entity_type="chat",
        )
        group_id = self._ensure_valid_group(default_group, "master")
            
        chat = ChatEntity(
            id=context.chat_id,
            interface=interface_name,
            title=context.chat_name,
            status=status,
            group_id=group_id,
        )
        self.save_chat(chat)
        return chat

    def save_chat(self, chat: ChatEntity):
        chat.interface = self.normalize_interface_name(chat.interface)
        path = os.path.join(self.chats_dir, f"{chat.interface}_{chat.id}.json")
        with open(path, "w") as f:
            f.write(chat.model_dump_json(indent=4))

    def list_entities(self, entity_type: str, interface: str = None, status: str = None) -> List[Dict]:
        target_dir = self.users_dir if entity_type == "users" else self.chats_dir
        results = []
        groups = self.policy.get("permission_groups", {})
        interface_filter = self.normalize_interface_name(interface) if interface else None
        if not os.path.exists(target_dir):
             return []
             
        for filename in os.listdir(target_dir):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(target_dir, filename), "r") as f:
                        data = json.load(f)
                        stored_interface = self.normalize_interface_name(data.get("interface"))
                        data["interface"] = stored_interface
                        if interface_filter and stored_interface != interface_filter:
                            continue
                        if status and data.get("status") != status:
                            continue
                        group_id = data.get("group_id")
                        group = groups.get(group_id, {})
                        data["group_name"] = group.get("name", group_id or "")
                        results.append(data)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to load identity file {filename}: {e}")
                    # Optionally clean up empty files
                    file_path = os.path.join(target_dir, filename)
                    if os.path.getsize(file_path) == 0:
                        logger.info(f"Removing empty identity file: {filename}")
                        os.remove(file_path)
        return results

class AccessController:
    def __init__(self, data_dir: str):
        self.identity_service = IdentityService(data_dir)

    @staticmethod
    def _merge_unique(*lists: List[str]) -> List[str]:
        merged: List[str] = []
        for source in lists:
            for item in source or []:
                if item and item not in merged:
                    merged.append(item)
        return merged

    def _resolve_context_entities(
        self,
        context: PrincipalContext,
    ) -> tuple[UserEntity, Optional[ChatEntity], Dict[str, Any]]:
        interface_name = self.identity_service.normalize_interface_name(context.interface)
        normalized_context = context
        if context.interface.lower() != interface_name:
            normalized_context = context.model_copy(update={"interface": interface_name})

        conf = self.identity_service.get_interface_config(interface_name)
        user = self.identity_service.get_user(interface_name, normalized_context.sender_id)
        if not user:
            user = self.identity_service.create_user(normalized_context)
            logger.info(f"New user registered: {user.display_name} ({user.id}) on {user.interface}")
        else:
            user = self.identity_service.ensure_user_group(user, interface_name, conf.get("dm_mode"))

        chat = None
        if normalized_context.is_group and normalized_context.chat_id:
            chat = self.identity_service.get_chat(interface_name, normalized_context.chat_id)
            if not chat:
                chat = self.identity_service.create_chat(normalized_context)
                logger.info(f"New chat registered: {chat.title} ({chat.id}) on {chat.interface}")
            else:
                chat = self.identity_service.ensure_chat_group(chat, interface_name, conf.get("group_mode"))

        return user, chat, conf

    def _collect_effective_rules(
        self,
        context: PrincipalContext,
        user: UserEntity,
        chat: Optional[ChatEntity],
    ) -> Dict[str, List[str]]:
        """
        Builds effective allow/deny rule sets from:
        group policy + user overrides (+ chat overrides on group messages).
        """
        if context.is_group and chat:
            target_entity = chat
        else:
            target_entity = user

        group_id = target_entity.group_id or user.group_id
        group = self.identity_service.get_permission_group(group_id) if group_id else None

        # Allow lists are evaluated by layer (group -> user -> entity) so that
        # user/chat overrides can narrow permissions even if group has wildcard.
        group_allow_actions = list(group.allow_actions if group else [])
        group_allow_capabilities = list(group.allow_capabilities if group else [])
        user_allow_actions = list(user.overrides.allow_actions)
        user_allow_capabilities = list(user.overrides.allow_capabilities)

        entity_allow_actions: List[str] = []
        entity_allow_capabilities: List[str] = []
        if context.is_group and chat:
            entity_allow_actions = list(chat.overrides.allow_actions)
            entity_allow_capabilities = list(chat.overrides.allow_capabilities)
        deny_actions = self._merge_unique(
            group.deny_actions if group else [],
            user.overrides.deny_actions,
            target_entity.overrides.deny_actions,
        )
        deny_capabilities = self._merge_unique(
            group.deny_capabilities if group else [],
            user.overrides.deny_capabilities,
            target_entity.overrides.deny_capabilities,
        )
        return {
            "group_id": [group_id] if group_id else [],
            "group_allow_actions": group_allow_actions,
            "group_allow_capabilities": group_allow_capabilities,
            "user_allow_actions": user_allow_actions,
            "user_allow_capabilities": user_allow_capabilities,
            "entity_allow_actions": entity_allow_actions,
            "entity_allow_capabilities": entity_allow_capabilities,
            "deny_actions": deny_actions,
            "deny_capabilities": deny_capabilities,
        }

    def _allow_layers_configured(self, rules: Dict[str, List[str]]) -> bool:
        return bool(
            rules.get("group_allow_actions")
            or rules.get("group_allow_capabilities")
            or rules.get("user_allow_actions")
            or rules.get("user_allow_capabilities")
            or rules.get("entity_allow_actions")
            or rules.get("entity_allow_capabilities")
        )

    def _is_allowed_by_layers(self, action_id: str, rules: Dict[str, List[str]]) -> bool:
        layers = [
            (rules.get("group_allow_actions", []), rules.get("group_allow_capabilities", [])),
            (rules.get("user_allow_actions", []), rules.get("user_allow_capabilities", [])),
            (rules.get("entity_allow_actions", []), rules.get("entity_allow_capabilities", [])),
        ]
        for allow_actions, allow_capabilities in layers:
            if not allow_actions and not allow_capabilities:
                continue
            if not (self._matches_any(action_id, allow_actions) or self._matches_any(action_id, allow_capabilities)):
                return False
        return True

    def pre_llm_gate(self, context: PrincipalContext) -> tuple[bool, str]:
        user, chat, conf = self._resolve_context_entities(context)

        if user.status == AccessStatus.BLOCKED:
            return False, "Sinto muito, seu acesso foi bloqueado pelo administrador."

        # Group check
        if context.is_group and context.chat_id:
            if chat.status == AccessStatus.BLOCKED:
                return False, "Este chat/grupo foi bloqueado pelo administrador."
            
            mode = conf.get("group_mode", "approved_only")
            allow_anyone = conf.get("allow_anyone_in_chats", [])
            
            if mode == "approved_only" and chat.status == AccessStatus.PENDING:
                if context.chat_id not in allow_anyone:
                    return False, "Este grupo aguarda aprovação do administrador para interagir."

        elif user.status == AccessStatus.PENDING:
            mode = conf.get("dm_mode", "approved_only")
            if mode == "approved_only":
                logger.warning(f"Access DENIED: User {context.sender_id} is pending on interface {context.interface}")
                return False, "Seu acesso está pendente de aprovação pelo administrador."

        return True, ""

    def pre_dispatch_gate(self, context: PrincipalContext, action: str, params: dict, capability_registry: Any = None, config_manager: Any = None) -> tuple[bool, str]:
        logger.debug(f"Pre-dispatch gate check: {action} for {context.sender_id} on {context.interface}")
        user, chat, conf = self._resolve_context_entities(context)

        if user.status == AccessStatus.BLOCKED:
            return False, "Seu acesso está bloqueado."

        if capability_registry and config_manager:
            if not self._is_action_enabled_by_config(action, capability_registry, config_manager):
                return False, f"Ação '{action}' está desativada na configuração atual."

        rules = self._collect_effective_rules(context, user, chat)

        # Allow rules are restrictive by layer (group + overrides).
        if self._allow_layers_configured(rules) and not self._is_allowed_by_layers(action, rules):
            return False, f"Ação '{action}' não está permitida para seu usuário."

        # Explicit Deny (group + overrides)
        if self._matches_any(action, rules["deny_actions"]):
            return False, f"Ação '{action}' negada explicitamente para você."
        if self._matches_any(action, rules["deny_capabilities"]):
            return False, f"Habilidade contendo '{action}' negada explicitamente para você."

        # Anyone mode restriction: Only low risk actions allowed
        mode = conf.get("group_mode" if context.is_group else "dm_mode", "approved_only")
        
        # If user is only allowed via 'anyone' mode (not manually approved)
        needs_anyone_check = False
        if mode == "anyone":
            if user.status != AccessStatus.APPROVED: # This logic depends on how 'anyone' status is stored
                needs_anyone_check = True
            
        if context.is_group:
            if chat and chat.status != AccessStatus.APPROVED and context.chat_id in conf.get("allow_anyone_in_chats", []):
                needs_anyone_check = True

        if needs_anyone_check:
            if not self._allow_anyone(action, capability_registry):
                return False, "Este comando requer aprovação manual do administrador (High Risk)."

        # Unapproved users should not execute high-risk actions even outside "anyone" mode.
        if user.status != AccessStatus.APPROVED and self._is_high_risk(action, capability_registry):
            return False, "Seu perfil ainda não está autorizado para ações de alto risco."

        return True, ""

    def get_allowed_actions(self, context: PrincipalContext, capability_registry: Any, config_manager: Any = None) -> List[str]:
        """
        Returns the list of actions the agent should see for this principal.
        This is intended for prompt filtering (least-privilege context),
        while pre_dispatch_gate remains the final execution authority.
        """
        if not context or not capability_registry:
            return []

        actions = capability_registry.list_actions()
        user, chat, conf = self._resolve_context_entities(context)
        mode = conf.get("group_mode" if context.is_group else "dm_mode", "approved_only")
        rules = self._collect_effective_rules(context, user, chat)

        # If allow lists are configured, they become restrictive by layer.
        has_allow_lists = self._allow_layers_configured(rules)

        filtered: List[str] = []
        for action_id in actions:
            # 1. Capability enablement from config (if available)
            if config_manager and not self._is_action_enabled_by_config(action_id, capability_registry, config_manager):
                continue

            # 2. Explicit deny rules (group + overrides)
            if self._matches_any(action_id, rules["deny_actions"]):
                continue
            if self._matches_any(action_id, rules["deny_capabilities"]):
                continue

            # 3. Optional explicit allow mode
            if has_allow_lists:
                if not self._is_allowed_by_layers(action_id, rules):
                    continue

            # 4. "anyone" mode receives low-risk subset by default
            if mode == "anyone" and user.status != AccessStatus.APPROVED and not self._allow_anyone(action_id, capability_registry):
                continue

            filtered.append(action_id)

        return sorted(set(filtered))

    def get_worker_policy(self, context: PrincipalContext) -> Dict[str, str]:
        """
        Returns worker visibility/control scopes for a principal context.
        Scopes: self_session | owner_session | owner_identity | global
        """
        user, chat, _ = self._resolve_context_entities(context)
        target_entity = chat if (context.is_group and chat) else user
        group_id = target_entity.group_id or user.group_id
        group = self.identity_service.get_permission_group(group_id) if group_id else None

        view_scope = str(getattr(group, "worker_view_scope", "owner_identity") or "owner_identity").strip().lower()
        control_scope = str(getattr(group, "worker_control_scope", "owner_identity") or "owner_identity").strip().lower()

        valid = {"self_session", "owner_session", "owner_identity", "global"}
        if view_scope not in valid:
            view_scope = "owner_identity"
        if control_scope not in valid:
            control_scope = "owner_identity"
        return {"view_scope": view_scope, "control_scope": control_scope}

    def resolve_principal_group_id(self, context: PrincipalContext) -> str:
        """
        Resolves effective group_id for a principal.
        This is useful for cross-cutting policies (e.g., permission approval governance).
        """
        user, chat, _ = self._resolve_context_entities(context)
        target_entity = chat if (context.is_group and chat) else user
        return str(target_entity.group_id or user.group_id or "").strip()

    def can_access_work(self, context: PrincipalContext, work_snapshot: Dict[str, Any], operation: str = "view") -> bool:
        """
        Checks whether principal can view/control a work item based on identity group policy.
        """
        policy = self.get_worker_policy(context)
        scope = policy["control_scope"] if operation == "control" else policy["view_scope"]

        requester_session = str(context.session_id or "").strip()
        requester_sender = str(context.sender_id or "").strip()
        work_session = str(work_snapshot.get("session_id") or "").strip()
        owner_session = str(work_snapshot.get("owner_session_id") or "").strip()
        favorite_session = str(work_snapshot.get("favorite_session_id") or "").strip()
        owner_sender = str(work_snapshot.get("owner_sender_id") or "").strip()
        favorite_sender = str(work_snapshot.get("favorite_sender_id") or "").strip()

        if scope == "global":
            return True
        if scope == "self_session":
            return requester_session and requester_session == work_session
        if scope == "owner_session":
            return requester_session and requester_session in {work_session, owner_session, favorite_session}
        if scope == "owner_identity":
            if requester_sender and requester_sender in {owner_sender, favorite_sender}:
                return True
            # Compatibility fallback when sender identity was not persisted on older works.
            if not owner_sender and not favorite_sender:
                return requester_session and requester_session in {work_session, owner_session, favorite_session}
            return False
        return False

    def _is_action_enabled_by_config(self, action_id: str, capability_registry: Any, config_manager: Any) -> bool:
        """
        Best-effort mapping from action -> module folder config key.
        Example module path: capabilities.system_control.capability -> system_control
        """
        try:
            capability = capability_registry.get_capability_for_action(action_id)
            if not capability:
                return False

            module_name = getattr(capability, "__module__", "")
            parts = module_name.split(".")
            # capabilities.<folder>.capability
            config_key = parts[1] if len(parts) >= 3 and parts[0] == "capabilities" else capability.name

            capabilities_cfg = config_manager.get("capabilities", {}) if config_manager else {}
            capability_cfg = capabilities_cfg.get(config_key, {})
            return capability_cfg.get("enabled", True)
        except Exception:
            # Fail-open for prompt visibility; dispatch gate remains authoritative.
            return True

    def _matches_any(self, action_id: str, patterns: List[str]) -> bool:
        for pattern in patterns or []:
            if not pattern:
                continue
            # Accept both explicit IDs and wildcard/prefix patterns.
            if fnmatch.fnmatch(action_id, pattern):
                return True
            if action_id.startswith(pattern.replace("*", "")):
                return True
        return False

    def _is_high_risk(self, action: str, capability_registry: Any = None) -> bool:
        if not (capability_registry and hasattr(capability_registry, "get_action_metadata")):
            logger.warning("Risk check failed closed | action=%s reason=registry_unavailable", action)
            return True
        try:
            metadata = capability_registry.get_action_metadata(action) or {}
        except Exception:
            logger.warning("Risk check failed closed | action=%s reason=metadata_lookup_error", action)
            return True
        if not metadata:
            logger.warning("Risk check failed closed | action=%s reason=metadata_missing", action)
            return True
        return str(metadata.get("risk_level", "")).lower() == "high"

    def _allow_anyone(self, action: str, capability_registry: Any = None) -> bool:
        if not (capability_registry and hasattr(capability_registry, "get_action_metadata")):
            logger.warning("Anyone-mode permission check failed closed | action=%s reason=registry_unavailable", action)
            return False
        try:
            metadata = capability_registry.get_action_metadata(action) or {}
        except Exception:
            logger.warning("Anyone-mode permission check failed closed | action=%s reason=metadata_lookup_error", action)
            return False
        if not metadata:
            logger.warning("Anyone-mode permission check failed closed | action=%s reason=metadata_missing", action)
            return False
        permissions = metadata.get("permissions") if isinstance(metadata.get("permissions"), dict) else {}
        return bool(permissions.get("allow_anyone", False))
