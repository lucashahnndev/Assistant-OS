import os
import requests
import asyncio
import logging
import html
import re
from telegram import Update, constants, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import threading

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramInterface:
    def __init__(self, token, router_process_func, allowed_users=None):
        """
        Initialize the Telegram Bot Interface.
        :param token: Telegram Bot Token
        :param router_process_func: Function to process text commands (from src/router.py)
        :param allowed_users: List of allowed User IDs (integers). If None, all users are allowed.
        """
        self.token = token
        self.router_process = router_process_func # Signature: (user_id, message, user_name, chat_id, chat_title, is_group, message_id, attachments)
        self.allowed_users = allowed_users
        self.application = None
        
        # Setup download directory
        self.download_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'data', 'downloads')
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

    def is_authorized(self, update: Update):
        if self.allowed_users is None:
            return True
        user_id = update.effective_user.id
        return user_id in self.allowed_users

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update):
            return
        await update.message.reply_text("Olá! Eu sou o assistant bot no Telegram. Envie comandos de texto ou arquivos.")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update):
            return

        text = update.message.text
        user_name = update.effective_user.first_name
        
        chat = update.effective_chat
        chat_id = chat.id
        chat_title = chat.title or chat.username or chat.first_name
        is_group = chat.type in ["group", "supergroup"]
        message_id = update.message.message_id
        
        # Process command via existing router
        try:
            logger.info(f"Processing command from {user_name} (Chat: {chat_id}): {text}")
            self.router_process(
                update.effective_user.id, 
                text, 
                user_name,
                chat_id,
                chat_title,
                is_group,
                message_id,
                attachments=None
            )
            # The async response system (Kernel -> Driver -> send_message_to) 
            # handles the actual content. We only return the work_id here.
        except Exception as e:
            logger.error(f"Error processing command: {e}")
            await update.message.reply_text("Ocorreu um erro ao processar seu comando.")

    async def handle_approval_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update):
            return
        query = update.callback_query
        if not query:
            return
        await query.answer()

        data = str(query.data or "").strip()
        if not data.startswith("apr|"):
            return

        parts = data.split("|")
        if len(parts) < 3:
            return

        work_id = str(parts[1] or "").strip()
        decision = str(parts[2] or "").strip().lower()
        scope = str(parts[3] or "worker").strip().lower() if len(parts) > 3 else "worker"
        if not work_id:
            await query.answer("Work inválida.", show_alert=True)
            return

        if decision == "deny":
            bridge_message = f"!approval {work_id} deny"
        else:
            if scope not in {"worker", "session", "global"}:
                scope = "worker"
            bridge_message = f"!approval {work_id} approve {scope}"

        try:
            chat = update.effective_chat
            user = update.effective_user
            self.router_process(
                user.id,
                bridge_message,
                user.first_name or "Unknown",
                chat.id if chat else None,
                (chat.title or chat.username or chat.first_name) if chat else None,
                bool(chat and chat.type in ["group", "supergroup"]),
                query.message.message_id if query.message else None,
                attachments=None
            )
            await query.answer("Decisão enviada.")
        except Exception as e:
            logger.error(f"Approval callback processing failed: {e}")
            await query.answer("Falha ao enviar decisão.", show_alert=True)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update):
            return
            
        file_id = update.message.document.file_id
        file_name = update.message.document.file_name
        
        # Route to process with attachment metadata
        caption = update.message.caption or ""
        self.router_process(
            update.effective_user.id,
            caption,
            update.effective_user.first_name,
            update.effective_chat.id,
            update.effective_chat.title or update.effective_chat.username,
            update.effective_chat.type in ["group", "supergroup"],
            update.message.message_id,
            attachments=[{"id": file_id, "name": file_name, "type": "document"}]
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_authorized(update):
            return
            
        file_id = update.message.photo[-1].file_id
        file_name = f"photo_{update.message.id}.jpg"
        
        # Route to process with photo metadata
        caption = update.message.caption or ""
        self.router_process(
            update.effective_user.id,
            caption,
            update.effective_user.first_name,
            update.effective_chat.id,
            update.effective_chat.title or update.effective_chat.username,
            update.effective_chat.type in ["group", "supergroup"],
            update.message.message_id,
            attachments=[{"id": file_id, "name": file_name, "type": "photo"}]
        )

    def run(self):
        """Starts the bot polling loop."""
        # Create a new event loop for this thread to avoid "set_wakeup_fd only works in main thread" error
        # Create a new event loop for this thread to avoid "set_wakeup_fd only works in main thread" error
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        
        self.application = Application.builder().token(self.token).build()

        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        self.application.add_handler(CallbackQueryHandler(self.handle_approval_callback, pattern=r"^apr\|"))

        async def _start():
            # Explicitly initialize to avoid ExtBot errors during startup/race conditions
            await self.application.initialize()
            await self.application.start()
            logger.info("Telegram Bot started polling...")
            # Use run_polling logic manually or just call it after init
            await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            
            # Keep alive
            while True:
                await asyncio.sleep(1)

        try:
            loop.run_until_complete(_start())
        except Exception as e:
            logger.error(f"Telegram Bot critical error: {e}")

    def start_in_thread(self):
        """Runs the bot in a separate thread to avoid blocking main thread."""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()

    def send_file_to(self, chat_id, file_path, caption=None):
        """
        Thread-safe method to send a file to a specific chat.
        """
        if not self.loop or not self.application:
            logger.error("Cannot send file: Bot loop not running.")
            return

        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return

        async def _send():
            try:
                formatted_caption = caption
                parse_mode = None
                
                if caption and caption.strip():
                    try:
                        import telegramify_markdown
                        formatted_caption = telegramify_markdown.markdownify(caption)
                        parse_mode = "MarkdownV2"
                    except ImportError:
                        logger.warning("telegramify-markdown not installed. Sending caption as raw text.")
                    except Exception as e:
                        logger.warning(f"Markdown formatting error for caption: {e}. Sending raw.")
                        formatted_caption = caption

                # Basic mime type detection by extension
                ext = os.path.splitext(file_path)[1].lower()
                with open(file_path, 'rb') as f:
                    if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                        await self.application.bot.send_photo(chat_id=chat_id, photo=f, caption=formatted_caption, parse_mode=parse_mode)
                    else:
                        await self.application.bot.send_document(chat_id=chat_id, document=f, caption=formatted_caption, parse_mode=parse_mode)
                logger.info(f"File sent to {chat_id}: {file_path}")
            except Exception as e:
                logger.error(f"Failed to send file to {chat_id}: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def send_message_to(self, chat_id, text):
        """
        Thread-safe method to send a text message to a specific chat.
        """
        if not self.loop or not self.application:
            logger.error("Cannot send message: Bot loop not running.")
            return

        async def _send():
            try:
                if not text or not text.strip():
                    logger.debug("Skipping empty message send.")
                    return
                
                # Apply telegram Markdown formatter natively at driver level
                formatted_text = text
                parse_mode = None
                try:
                    import telegramify_markdown
                    formatted_text = telegramify_markdown.markdownify(text)
                    parse_mode = "MarkdownV2"
                except ImportError:
                    logger.warning("telegramify-markdown not installed. Sending as raw text.")
                except Exception as e:
                    logger.warning(f"Markdown formatting error: {e}. Sending raw.")
                    formatted_text = text

                await self.application.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=parse_mode)
                logger.info(f"Message sent to {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send message to {chat_id}: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def send_action_to(self, chat_id, action="typing"):
        """
        Thread-safe method to send a chat action (like typing) to a specific chat.
        """
        if not self.loop or not self.application:
            return

        async def _send():
            try:
                # Map string action to constant if needed
                tg_action = action
                if action == "typing":
                    tg_action = constants.ChatAction.TYPING
                
                await self.application.bot.send_chat_action(chat_id=int(chat_id), action=tg_action)
                logger.info(f"Chat action '{action}' sent to {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send chat action to {chat_id}: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def send_approval_request(self, chat_id, work_id, prompt, options=None):
        """
        Thread-safe method to send approval request with inline buttons.
        """
        if not self.loop or not self.application:
            logger.error("Cannot send approval request: Bot loop not running.")
            return

        work_id = str(work_id or "").strip()
        if not work_id:
            logger.error("Cannot send approval request without work_id.")
            return

        prompt_text = str(prompt or "This worker needs your approval to continue.").strip()
        def _to_html_with_code_blocks(text: str) -> str:
            # Convert `code` spans to Telegram HTML <pre> blocks for better visibility.
            chunks = re.split(r"`([^`]+)`", text or "")
            out = []
            for idx, chunk in enumerate(chunks):
                if idx % 2 == 1:
                    code = html.escape(str(chunk or "").strip())
                    if code:
                        out.append(f"\n<pre>{code}</pre>\n")
                else:
                    plain = html.escape(str(chunk or ""))
                    if plain:
                        out.append(plain)
            rendered = "".join(out).strip()
            return rendered or html.escape(text or "")

        prompt_html = _to_html_with_code_blocks(prompt_text)
        pretty_prompt = (
            "⚠️ <b>Permission approval required</b>\n\n"
            f"{prompt_html}\n\n"
            "<i>Choose one option below to continue.</i>"
        )
        provided = options if isinstance(options, list) else []
        label_map = {str(o.get("id")): str(o.get("label")) for o in provided if isinstance(o, dict)}

        buttons = [
            InlineKeyboardButton(f"❌ {label_map.get('deny', 'Deny')}", callback_data=f"apr|{work_id}|deny"),
            InlineKeyboardButton(f"✅ {label_map.get('approve_worker', 'Allow this worker')}", callback_data=f"apr|{work_id}|approve|worker"),
        ]
        buttons_row2 = [
            InlineKeyboardButton(f"🧩 {label_map.get('approve_session', 'Allow this session')}", callback_data=f"apr|{work_id}|approve|session"),
            InlineKeyboardButton(f"🌍 {label_map.get('approve_global', 'Allow global')}", callback_data=f"apr|{work_id}|approve|global"),
        ]
        markup = InlineKeyboardMarkup([buttons, buttons_row2])

        async def _send():
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=pretty_prompt,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                logger.info(f"Approval request sent to {chat_id} for work {work_id}")
            except Exception as e:
                logger.error(f"Failed to send approval request to {chat_id}: {e}")

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    async def _download(self, file_id, target_path):
        try:
            file = await self.application.bot.get_file(file_id)
            await file.download_to_drive(target_path)
            logger.info(f"File {file_id} downloaded to {target_path}")
            return target_path
        except Exception as e:
            logger.error(f"Failed to download file {file_id}: {e}")
            return None

    def download_file(self, file_id, target_path):
        """
        Thread-safe method to download a file from Telegram.
        """
        if not self.loop or not self.application:
            return None
            
        future = asyncio.run_coroutine_threadsafe(self._download(file_id, target_path), self.loop)
        return future.result() # This blocks the calling thread until download is done

    async def _download_user_profile_photo(self, user_id, target_path):
        try:
            photos = await self.application.bot.get_user_profile_photos(user_id, limit=1)
            if photos.total_count > 0:
                file_id = photos.photos[0][-1].file_id # Get largest size
                file = await self.application.bot.get_file(file_id)
                await file.download_to_drive(target_path)
                logger.info(f"Profile photo for {user_id} downloaded to {target_path}")
                return target_path
            return None
        except Exception as e:
            logger.error(f"Failed to download profile photo for {user_id}: {e}")
            return None

    def download_user_profile_photo(self, user_id, target_path):
        """
        Thread-safe method to download a user's profile photo from Telegram.
        """
        if not self.loop or not self.application:
            return None
            
        future = asyncio.run_coroutine_threadsafe(self._download_user_profile_photo(user_id, target_path), self.loop)
        return future.result()
