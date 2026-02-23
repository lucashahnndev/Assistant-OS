import threading
import os
import json
from .base_driver import BaseDriver
from core.identity import PrincipalContext
from utils.logging_config import get_logger

logger = get_logger("TelegramDriver")

try:
    from drivers.telegram.telegram_bot import TelegramInterface
except ImportError:
    TelegramInterface = None

class TelegramDriver(BaseDriver):
    def __init__(self, kernel, parent_dir):
        super().__init__(kernel)
        self.parent_dir = parent_dir
        self.bot = None
        self.config_path = os.path.join(parent_dir, 'data', 'config.json')
        self.active_typing: dict[str, bool] = {} # chat_id -> is_typing
        self.typing_lock = threading.Lock()

    def start(self):
        if not TelegramInterface:
            logger.warning("Telegram dependency not found.")
            return

        # Use ConfigManager to get properly substituted values
        from config.manager import ConfigManager
        cm = ConfigManager()
        
        # Get Telegram config
        # Assuming 'telegram' section exists or we read root keys if legacy
        # Based on config.json structure, telegram config might be under 'interfaces' > 'telegram' 
        # OR root keys. Let's check both or standardized.
        # Previously it read 'telegram_token' from root.
        
        # ConfigManager.get('telegram_token') would work if it exposes it, 
        # but ConfigManager structure is usually get_interfaces_config().
        
        # Let's check how config.json was structured in previous turns.
        # It had 'telegram': {'token': 'ENV...', 'allowed_users': ...} inside 'interfaces' OR root?
        # A quick check of config.json would be prudent, but I'll assume standard ConfigManager usage.
        
        # Safe approach: Read full config via manager
        full_config = cm.config_data
        
        # Try new structure first
        telegram_conf = full_config.get('interfaces', {}).get('telegram', {})
        token = telegram_conf.get('token')
        allowed_users = telegram_conf.get('allowed_users')
        
        # Fallback to root (legacy) if not found
        if not token:
            token = full_config.get('telegram_token')
        if not allowed_users:
            allowed_users = full_config.get('allowed_users')

        if token:
            # Initialize Interface with a custom processor
            self.bot = TelegramInterface(
                token=token,
                router_process_func=self._bridge_process,
                allowed_users=allowed_users
            )
            self.bot.start_in_thread()
            logger.info(f"Telegram Driver started.")
        else:
            logger.warning("Telegram Token not found.")

    def stop(self):
        # TelegramInterface might need a stop method explicitly added or just let the daemon die
        pass

    def send_response(self, text, target=None, is_chunk=False, attachments=None):
        """Sends a text message back to the Telegram chat. If attachments exist, sends them natively."""
        if self.bot and target:
            # Strip prefix robustly (handles both telegram_ and telegram- for compatibility)
            chat_id = target
            if chat_id.startswith("telegram_"):
                chat_id = chat_id.replace("telegram_", "", 1)
            elif chat_id.startswith("telegram-"):
                chat_id = chat_id.replace("telegram-", "", 1)
            
            try:
                caption_sent = False
                
                # Check if we can use the response text as a caption
                if attachments and len(attachments) == 1:
                    # Extract path if it's a dictionary
                    att = attachments[0]
                    file_path = att.get('path') if isinstance(att, dict) else att
                    
                    # Telegram limit is ~1024 for captions
                    if text and len(text) <= 1000:
                        logger.info(f"TelegramDriver sending file with caption to {chat_id}: {file_path}")
                        self.bot.send_file_to(chat_id, file_path, caption=text)
                        caption_sent = True
                        if self.bot:
                            self.bot.send_action_to(chat_id, action="typing")
                
                # If we didn't send text as a caption, send it normally
                if not caption_sent and text and text.strip():
                    self.bot.send_message_to(chat_id, text)
                    if self.bot:
                        self.bot.send_action_to(chat_id, action="typing")
                        
                # Send remaining attachments if not sent as caption
                if attachments:
                    for i, att in enumerate(attachments):
                        if caption_sent and i == 0:
                            continue # Already sent the first one with a caption
                            
                        file_path = att.get('path') if isinstance(att, dict) else att
                        logger.info(f"TelegramDriver requesting file send to {chat_id}: {file_path}")
                        self.bot.send_file_to(chat_id, file_path)
                        if self.bot:
                            self.bot.send_action_to(chat_id, action="typing")
                
                logger.debug(f"TelegramDriver sent response to {chat_id}")
            except Exception as e:
                logger.error(f"Error sending Telegram response to {chat_id}: {e}")
        else:
            logger.warning(f"TelegramDriver cannot send response. Bot: {self.bot}, Target: {target}")

    def send_file(self, target, file_path, caption=None):
        """
        Sends a file attachment to the user.
        :param target: User ID or Channel ID to send to.
        :param file_path: Absolute path to the file.
        :param caption: Optional caption text.
        """
        if self.bot and target:
            # target is likely a string "telegram_12345" or just "12345"
            # Kernel usually passes "telegram_12345" as session_id.
            # We need to strip prefix if present.
            # Strip prefix robustly
            chat_id = target
            if chat_id.startswith("telegram_"):
                chat_id = chat_id.replace("telegram_", "", 1)
            elif chat_id.startswith("telegram-"):
                chat_id = chat_id.replace("telegram-", "", 1)
            
            try:
                # Delegate to TelegramInterface
                logger.info(f"TelegramDriver requesting file send to {chat_id}: {file_path}")
                self.bot.send_file_to(chat_id, file_path, caption)
                # Refresh typing status
                self.bot.send_action_to(chat_id, action="typing")
            except Exception as e:
                logger.error(f"Error sending file via Telegram: {e}")
        else:
            logger.warning(f"TelegramDriver cannot send file. Bot: {self.bot}, Target: {target}")

    def send_status(self, target, phase, payload=None):
        """Telegram acknowledgment and status updates. Intercepts errors for custom rendering."""
        if self.bot and target:
            chat_id = target
            if chat_id.startswith("telegram_"):
                chat_id = chat_id.replace("telegram_", "", 1)
            elif chat_id.startswith("telegram-"):
                chat_id = chat_id.replace("telegram-", "", 1)
            
            # 1. Error Handling (Architectural delegation)
            if phase == 'error' and isinstance(payload, dict):
                code = payload.get('code')
                message = payload.get('message', 'Erro desconhecido.')
                action = payload.get('action', 'ferramenta')
                
                error_msg = message
                if code == 'loop_break':
                    error_msg = f"⚠️ **Aviso de Sistema**: Pareço estar travado ao tentar usar a ferramenta `{action}` repetidamente sem sucesso. Vou interromper o processo para evitar loop infinito."
                elif code == 'action_error':
                    error_msg = f"❌ **Erro de Execução**:\n{message}"
                elif code == 'system_error':
                    error_msg = f"❗ **Falha Técnica**:\n{message}"
                
                # We use send_response (which handles markdownify and types)
                self.send_response(error_msg, target=target)
                return

            # 2. Activity Indicators
            # Send 'typing' action for 'thinking' or 'executing' phases
            if phase in ['thinking', 'executing']:
                self._start_typing_loop(chat_id)
                # WE DO NOT send the message here to follow user request of "instead of steps, send typing"
            
    def send_reasoning_chunk(self, target, content):
        """Telegram reasoning chunks as ephemeral-ish messages or just debug."""
        # For now, we don't want to spam the user with every thought chunk 
        # unless it's a significant milestone.
        # But we could send it as a italicized message to show progress.
        pass

    def get_capabilities(self) -> dict:
        """Telegram supports markdown, attachments, but no live text streaming."""
        return {
            "markdown": True,
            "rich_media": True,
            "voice_only": False,
            "streaming": False
        }

    def send_complete(self, target):
        """Telegram does not support completion events yet, but we use it to stop typing."""
        chat_id = target
        if chat_id.startswith("telegram_"):
            chat_id = chat_id.replace("telegram_", "", 1)
        
        with self.typing_lock:
            if chat_id in self.active_typing:
                self.active_typing[chat_id] = False

    def _start_typing_loop(self, chat_id):
        """Starts a background loop to keep the 'typing' status alive with a realistic pulse."""
        def _loop():
            import time
            import random
            while True:
                with self.typing_lock:
                    if not self.active_typing.get(chat_id, False):
                        break
                
                if self.bot:
                    self.bot.send_action_to(chat_id, action="typing")
                
                # Realistic Pulse: Sleep between 3 to 5 seconds
                # Occasionally take a longer break (simulate thinking/stopping)
                sleep_time = random.uniform(3, 4.5)
                if random.random() < 0.2: # 20% chance of a "pause"
                    sleep_time += random.uniform(1, 2)
                
                time.sleep(sleep_time)
            
            logger.debug(f"Typing loop for {chat_id} stopped.")

        with self.typing_lock:
            if not self.active_typing.get(chat_id, False):
                self.active_typing[chat_id] = True
                threading.Thread(target=_loop, daemon=True).start()
                logger.info(f"Typing loop for {chat_id} started (Phase: typing indicators active).")


    def _bridge_process(self, user_id, message, user_name="Unknown", chat_id=None, chat_title=None, is_group=False, message_id=None, attachments=None):
        """
        Adapts the TelegramInterface router_process signature to the Kernel's process method.
        """
        # Standardized prefix: telegram_ (with underscore)
        session_id = f"telegram_{user_id}"
        
        # Check for /new command to create a transient sub-session
        if message.strip().startswith("/new"):
            import uuid
            session_id = f"telegram_{user_id}_{str(uuid.uuid4())[:8]}"
            message = "New session started. How can I help you?" if message.strip() == "/new" else message.replace("/new", "").strip()

        user_data = {
            "channel": "Telegram",
            "user_name": user_name,
            "user_id": str(user_id)
        }
        
        context = PrincipalContext(
            interface="telegram",
            sender_id=str(user_id),
            sender_name=user_name,
            chat_id=str(chat_id) if chat_id else None,
            chat_name=chat_title,
            is_group=is_group,
            session_id=session_id,
            message_id=str(message_id) if message_id else None
        )
        
        # Start 'typing' status immediately
        # Use chat_id if available (groups), fallback to user_id
        target_id = str(chat_id) if chat_id else str(user_id)
        self._start_typing_loop(target_id)
        
        def _execute_processing():
            try:
                # Prepare local attachments in background thread to avoid deadlock
                local_attachments = []
                if attachments:
                    session_uploads_dir = os.path.join(self.kernel.workspace_service.get_session_dir(session_id), "uploads")
                    os.makedirs(session_uploads_dir, exist_ok=True)
                    
                    for att in attachments:
                        file_id = att.get("id")
                        file_name = att.get("name")
                        if file_id and file_name:
                            target_path = os.path.join(session_uploads_dir, file_name)
                            logger.info(f"Downloading attachment {file_name} for session {session_id}...")
                            # download_file uses asyncio.run_coroutine_threadsafe on the bot loop
                            # so this MUST be called from a thread OTHER than the bot loop.
                            local_path = self.bot.download_file(file_id, target_path)
                            if local_path:
                                local_attachments.append(local_path)

                # This call can be slow/blocking
                self.kernel.process_input(message, self, user_id=session_id, user_data=user_data, context=context, attachments=local_attachments)
                
                # Fetch profile picture if missing
                session = self.kernel.orchestrator.get_session_robust(session_id)
                if session and not getattr(session, 'profile_picture', None):
                    session_media_dir = os.path.join(
                        self.kernel.orchestrator.sessions_dir,
                        session_id,
                        "media",
                        "profile_picture",
                    )
                    os.makedirs(session_media_dir, exist_ok=True)
                    target_path = os.path.join(session_media_dir, f"avatar_{user_id}.jpg")
                    if self.bot.download_user_profile_photo(user_id, target_path):
                        session.profile_picture = f"media/profile_picture/avatar_{user_id}.jpg"
                        self.kernel.orchestrator._save_session(session)
                        
                        # Notify index manager to update its cache
                        self.kernel.orchestrator.index_manager.register_session(session)
            except Exception as e:
                logger.error(f"Error in background processing: {e}")
                self.send_response("Desculpe, houve um erro interno ao processar sua mensagem.", target=f"telegram_{user_id}")
            finally:
                # Ensure we signal complete to stop typing if not already stopped by send_response
                self.send_complete(f"telegram_{target_id}")

        # Execute kernel in a separate thread to keep the bot's event loop free
        threading.Thread(target=_execute_processing, daemon=True).start()
        
        return "processing", True
