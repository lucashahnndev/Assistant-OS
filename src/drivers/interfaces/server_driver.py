import threading
import uvicorn
import asyncio
import os
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Any, Dict, Optional
import json
import time
import re
from http.cookies import SimpleCookie
from .base_driver import BaseDriver
from core.identity import PrincipalContext
from utils.logging_config import get_logger
from server.main import create_app
from server.auth import decode_access_token

logger = get_logger("ServerDriver")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, set] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)
        total = sum(len(s) for s in self.active_connections.values())
        logger.info(f"Client connected: {session_id}. Total: {total}")

    def disconnect(self, session_id: str, websocket: WebSocket = None):
        if session_id in self.active_connections:
            if websocket is not None:
                self.active_connections[session_id].discard(websocket)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
            else:
                del self.active_connections[session_id]
            logger.info(f"Client disconnected: {session_id}")

    async def broadcast(self, message: str):
        dead = []
        for session_id, sockets in self.active_connections.items():
            for connection in list(sockets):
                try:
                    await connection.send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to {session_id}: {e}")
                    dead.append((session_id, connection))
        for session_id, ws in dead:
            self.active_connections.get(session_id, set()).discard(ws)

    async def send_personal_message(self, message: str, session_id: str):
        sockets = self.active_connections.get(session_id, set())
        dead = []
        for ws in list(sockets):
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to {session_id}: {e}")
                dead.append(ws)
        for ws in dead:
            sockets.discard(ws)

class ServerDriver(BaseDriver):
    def __init__(self, kernel, parent_dir):
        super().__init__(kernel, interface_id="web")
        self.parent_dir = parent_dir
        # Use our new Portal API factory
        self.app = create_app(kernel=self.kernel)
        self.connection_manager = ConnectionManager()
        self.server_thread = None
        # Load config
        server_config = self.kernel.config_manager.get_interfaces_config().get('server', {})
        self.host = server_config.get('host', "0.0.0.0")
        self.port = server_config.get('port', 8000)
        tls_config = server_config.get("tls", {}) if isinstance(server_config.get("tls"), dict) else {}
        base_data_dir = getattr(self.kernel.config_manager, "base_data_dir", os.path.join(os.getcwd(), "data"))
        cert_default = os.path.join(base_data_dir, "certs", "localhost.crt")
        key_default = os.path.join(base_data_dir, "certs", "localhost.key")
        self.tls_enabled = bool(tls_config.get("enabled", True))
        self.ssl_certfile = tls_config.get("certfile") or cert_default
        self.ssl_keyfile = tls_config.get("keyfile") or key_default
        self.running = False
        self.loop = None
        self.loop_ready = threading.Event()
        
        self._setup_extra_routes()
        
        # Initialize VoiceManager for the new protocol
        from server.voice_manager import VoiceManager
        self.voice_manager = VoiceManager(self)

    def _normalize_ws_event(self, event: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
        """Adds a minimal, backwards-compatible envelope to outbound WS events."""
        normalized = dict(event or {})
        event_type = str(normalized.get("event_type") or normalized.get("type") or "").strip()
        if event_type and not normalized.get("event_type"):
            normalized["event_type"] = event_type
        if event_type and not normalized.get("type"):
            normalized["type"] = event_type
        if "event_id" not in normalized or not normalized.get("event_id"):
            normalized["event_id"] = str(uuid.uuid4())
        if session_id and not normalized.get("session_id"):
            normalized["session_id"] = session_id
        if "timestamp" not in normalized or normalized.get("timestamp") in (None, ""):
            normalized["timestamp"] = time.time()
        normalized.setdefault("channel", "websocket")
        normalized.setdefault("interface", self.get_interface_id())
        normalized.setdefault("source", "server_driver")
        return normalized

    def _setup_extra_routes(self):
        @self.app.on_event("startup")
        async def startup_event():
            self.loop = asyncio.get_running_loop()
            self.loop_ready.set()
            logger.info("ServerDriver: Captured asyncio loop and set ready event.")
            
            # Bridge global_event_bus to WebSockets
            from utils.event_bus import global_event_bus
            global_event_bus.set_loop(self.loop)
            
            # Start Wegena Scene Observer conditionally
            try:
                from services.wegena_observer import WegenaSceneObserver
                self.wegena_observer = WegenaSceneObserver()
                self.wegena_observer.start()
                logger.info("ServerDriver: Wegena Scene Observer started successfully.")
            except Exception as e:
                logger.error(f"ServerDriver: Failed to initialize Wegena Scene Observer: {e}")
            
            async def event_bridge():
                queue = global_event_bus.subscribe()
                try:
                    while True:
                        event = await queue.get()
                        
                        # FILTER DUPLICATES: Skip events that are already sent via 
                        # direct driver callback methods (send_status, send_reasoning_chunk, send_complete)
                        # to avoid duplication in the Web UI.
                        if event.get("type") in ["status", "reasoning_chunk", "complete"]:
                            continue
                        
                        target = event.get("session_id")
                        normalized_event = self._normalize_ws_event(event, session_id=target)
                        payload = json.dumps(normalized_event)
                        
                        # List-affecting events should be broadcasted so ALL connected clients
                        # (even if on different active sessions) see the updates in their sidebar.
                        if normalized_event.get("type") in ["session_updated", "unread_count_updated", "message_added"]:
                            logger.debug(f"Broadcasting event: {normalized_event.get('type')} to all clients")
                            await self.connection_manager.broadcast(payload)
                        elif normalized_event.get("type") == "weg_scene":
                            # Broadcast or send weg_scene event directly
                            logger.info(f"Broadcasting weg_scene event to all clients for session {target}")
                            await self.connection_manager.broadcast(payload)
                        elif target:
                             logger.debug(f"Sending event: {normalized_event.get('type')} to session {target}")
                             await self.connection_manager.send_personal_message(payload, target)
                        else:
                             logger.debug(f"Broadcasting generic event: {normalized_event.get('type')}")
                             await self.connection_manager.broadcast(payload)
                except Exception as e:
                    logger.error(f"Error in EventBus-to-WS bridge: {e}")
                finally:
                    global_event_bus.unsubscribe(queue)
            
            asyncio.create_task(event_bridge())

        @self.app.on_event("shutdown")
        async def shutdown_event():
            from utils.event_bus import global_event_bus
            logger.info("ServerDriver shutdown event: clearing EventBus loop reference.")
            global_event_bus.set_loop(None)
            
            if hasattr(self, 'wegena_observer') and self.wegena_observer:
                try:
                    self.wegena_observer.stop()
                except Exception as e:
                    logger.error(f"ServerDriver: Error stopping Wegena Scene Observer: {e}")
            
            self.loop = None
            self.loop_ready.clear()

        @self.app.websocket("/ws/{session_id}")
        async def websocket_endpoint(websocket: WebSocket, session_id: str):
            await self.connection_manager.connect(websocket, session_id)
            sender_id, sender_name = self._extract_identity_from_cookie(
                websocket.headers.get("cookie", ""),
                session_id,
            )
            try:
                while True:
                    data = await websocket.receive_text()
                    # logger.info(f"Received from client {session_id}: {data}")
                    
                    # Parse JSON if possible
                    try:
                        message_data = json.loads(data)
                        content = message_data.get("content", "")
                        msg_type = message_data.get("type", "msg")
                        attachments = message_data.get("attachments", [])
                        user_data = message_data.get("user_data", {}) or {}
                    except:
                        content = data
                        msg_type = "msg"
                        attachments = []
                        user_data = {}

                    if msg_type == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                        continue

                    # VOICE PROTOCOL HANDLERS
                    if msg_type == "session.start":
                        logger.info(f"Voice session start requested: {session_id}")
                        await websocket.send_text(json.dumps({
                            "type": "server.ready", 
                            "sessionId": session_id,
                            "features": {"vad": True, "asrPartial": True, "ttsStream": True}
                        }))
                        continue
                    
                    if msg_type == "input.audio.chunk":
                        # Log every 20 chunks to avoid spam
                        if not hasattr(self, '_chunk_count'): self._chunk_count = 0
                        self._chunk_count += 1
                        if self._chunk_count % 20 == 0:
                            logger.debug(f"Received audio chunk {self._chunk_count} for {session_id}")
                        
                        self.voice_manager.handle_chunk(session_id, message_data.get("b64", ""))
                        continue
                    
                    if msg_type == "input.audio.end":
                        self.voice_manager.handle_end(session_id)
                        continue
                    
                    if msg_type == "control.cancel":
                        # Interruption logic
                        # Not fully implemented in P0, but signal received
                        continue

                    # Boot sequence sentinel — replace with the actual diagnostic prompt
                    # so the agent uses its real tools instead of receiving a literal token.
                    if content == '__BOOT_SEQUENCE__' and session_id == 'system.boot':
                        locale = (user_data or {}).get('locale', 'pt-BR')
                        resolved_name = sender_name or 'Administrator'

                        # Reset session history before each boot so accumulated previous
                        # boots don't confuse the LLM (prevents "Append-only protection" spam).
                        try:
                            session = self.kernel.orchestrator.get_session_robust(session_id)
                            if session and hasattr(session, 'clear_history'):
                                session.clear_history()
                                logger.info(f"Boot: cleared session history for {session_id}")
                        except Exception as e:
                            logger.warning(f"Boot: could not clear session history: {e}")

                        content = (
                            f"SYSTEM BOOT SEQUENCE INITIATED.\n"
                            f"The user '{resolved_name}' has just logged in.\n"
                            f"Your task is to act as the OS Kernel and perform a boot diagnostic.\n"
                            f"1. Use 'system.control.info' and 'system.control.status' to check system health.\n"
                            f"2. Use 'cloudflare.tunnel.status' or 'ngrok.tunnel.status' to check active network tunnels.\n"
                            f"3. Finally, synthesize this information into a brief, welcoming boot briefing.\n"
                            f"CRITICAL: Do NOT output generic text. Use your tools. "
                            f"RESPOND EXPLICITLY IN THE FOLLOWING LOCALE/LANGUAGE: {locale}"
                        )

                    # Process in background thread to avoid blocking WebSocket loop
                    threading.Thread(
                        target=self._process_message,
                        args=(content, session_id, attachments, user_data, sender_id, sender_name),
                     ).start()
                     
            except WebSocketDisconnect:
                self.connection_manager.disconnect(session_id, websocket)
            except Exception as e:
                logger.error(f"WebSocket Error: {e}")
                self.connection_manager.disconnect(session_id, websocket)
 
        @self.app.get("/status")
        async def status():
            return {
                "status": "running",
                "drivers": [driver.__class__.__name__ for driver in self.kernel.drivers]
            }
            
        @self.app.post("/webhook")
        async def webhook(data: dict):
            logger.info(f"Webhook received: {data}")
            # Example: {"event": "alert", "message": "Server Down"}
            if "message" in data:
                 threading.Thread(target=self._process_message, args=(data["message"], "webhook")).start()
            return {"status": "received"}
 
    @staticmethod
    def _extract_identity_from_cookie(cookie_header: str, session_id: str) -> tuple[str, str | None]:
        """
        Resolves the principal identity for web messages.
        Prefers authenticated portal user from JWT cookie; falls back to session-scoped id.
        """
        fallback_sender = session_id
        if not cookie_header:
            return fallback_sender, None

        try:
            parsed = SimpleCookie()
            parsed.load(cookie_header)
            token_cookie = parsed.get("access_token")
            if not token_cookie:
                return fallback_sender, None

            token = token_cookie.value or ""
            if token.startswith("Bearer "):
                token = token.split(" ", 1)[1]

            payload = decode_access_token(token)
            if not payload:
                return fallback_sender, None

            uid = payload.get("uid")
            username = payload.get("sub")
            if uid is not None:
                sender_id = f"user_{uid}"
            elif username:
                safe_username = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(username))
                sender_id = f"user_{safe_username}"
            else:
                sender_id = fallback_sender

            return sender_id, username
        except Exception:
            return fallback_sender, None

    def _process_message(
        self,
        message,
        session_id="default",
        attachments=None,
        user_data=None,
        sender_id=None,
        sender_name=None,
    ):
         # Send to Kernel with Correct Session ID
         resolved_sender = sender_id or session_id
         context = PrincipalContext(
             interface="web",
             sender_id=resolved_sender,
             sender_name=sender_name,
             session_id=session_id
         )
         safe_user_data = user_data if isinstance(user_data, dict) else {}
         if sender_name and not safe_user_data.get("user_name"):
             safe_user_data["user_name"] = sender_name

         driver_instance = self
         if safe_user_data.get('is_boot') and safe_user_data.get('is_voice_active') and hasattr(self, 'voice_manager'):
             import time, re
             class BootVoiceWrapper:
                 def __init__(self, driver, sid):
                     self.driver = driver
                     self.sid = sid
                     self.buffer = ""
                     self.turn_id = f"boot_{int(time.time())}"
                     
                 def send_response(self, text, target=None, is_chunk=False, attachments=None, model_info=None, **kwargs):
                     result = self.driver.send_response(text, target, is_chunk, attachments, model_info, **kwargs)
                     raw = str(text or "")
                     if not raw: return
                     from utils.voice_text import sanitize_tts_text
                     speech_text = sanitize_tts_text(raw)
                     if not speech_text: return
                     self.buffer += speech_text
                     parts = re.split(r'([.?!]|\n)', self.buffer)
                     if len(parts) > 2:
                         to_queue = ""
                         for i in range(0, len(parts) - 1, 2):
                             to_queue += parts[i] + parts[i+1]
                         self.buffer = parts[-1]
                         if to_queue.strip():
                             self.driver.voice_manager._ensure_engines()
                             if not self.driver.voice_manager.tts_manager:
                                 from services.tts.manager import TTSManager
                                 self.driver.voice_manager.tts_manager = TTSManager()
                             self.driver.voice_manager._queue_tts(self.sid, self.turn_id, to_queue.strip())
                     return result
                             
                 def send_complete(self, target=None, *args, **kwargs):
                     if self.buffer.strip():
                         self.driver.voice_manager._ensure_engines()
                         if not self.driver.voice_manager.tts_manager:
                             from services.tts.manager import TTSManager
                             self.driver.voice_manager.tts_manager = TTSManager()
                         self.driver.voice_manager._queue_tts(self.sid, self.turn_id, self.buffer.strip())
                     ctx = self.driver.voice_manager.get_context(self.sid)
                     ctx.tts_queue.put((self.turn_id, None)) # EOF sentinel
                     if hasattr(self.driver, 'send_complete'):
                         self.driver.send_complete(target, *args, **kwargs)

                 def send_status(self, *args, **kwargs):
                     self.driver.send_status(*args, **kwargs)
                 def get_capabilities(self):
                     return getattr(self.driver, 'get_capabilities', lambda: [])()
                 def get_interface_id(self):
                     return getattr(self.driver, 'get_interface_id', lambda: "web")()

             driver_instance = BootVoiceWrapper(self, session_id)

         self.kernel.process_input(
             message,
             driver_instance,
             user_id=session_id,
             user_data=safe_user_data,
             context=context,
             attachments=attachments,
         )

    def start(self):
        logger.debug("ServerDriver.start() called")
        self.running = True
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        logger.info(f"Server Driver started on {self.host}:{self.port}")

    def _run_server(self):
        # Uvicorn needs to run passing the app object
        # Since we are inside a class, we pass the app instance directly
        # But uvicorn.run blocks.
        try:
            run_kwargs = {"host": self.host, "port": self.port}
            if self.tls_enabled:
                cert_ok = os.path.isfile(self.ssl_certfile)
                key_ok = os.path.isfile(self.ssl_keyfile)
                if cert_ok and key_ok:
                    run_kwargs["ssl_certfile"] = self.ssl_certfile
                    run_kwargs["ssl_keyfile"] = self.ssl_keyfile
                    logger.info(f"Attempting to start Uvicorn on https://{self.host}:{self.port}")
                else:
                    logger.warning(
                        "TLS enabled but cert/key not found (%s, %s). Falling back to HTTP.",
                        self.ssl_certfile,
                        self.ssl_keyfile,
                    )
                    logger.info(f"Attempting to start Uvicorn on http://{self.host}:{self.port}")
            else:
                logger.info(f"Attempting to start Uvicorn on http://{self.host}:{self.port}")
            uvicorn.run(self.app, **run_kwargs)
            logger.info("Uvicorn stopped.")
        except Exception as e:
            logger.error(f"Server start error: {e}", exc_info=True)
        finally:
            # If startup failed (e.g., port already in use) or server stopped,
            # prevent stale closed loop references from breaking the kernel.
            from utils.event_bus import global_event_bus
            global_event_bus.set_loop(None)
            self.loop = None
            self.loop_ready.clear()

    def stop(self):
        self.running = False
        # Uvicorn doesn't have a clean stop from thread easily without access to the server object
        # But setting daemon=True on thread helps.
        pass

    def _get_session_stream_context(self, session_id: str):
        session = None
        context = None
        if self.kernel and getattr(self.kernel, "orchestrator", None):
            try:
                session = self.kernel.orchestrator.get_session_robust(session_id)
            except Exception:
                session = None
        if session and isinstance(getattr(session, "context", None), dict):
            context = session.context
        return session, context

    def _ensure_response_stream(self, session_id: str):
        session, context = self._get_session_stream_context(session_id)
        stream_id = None
        stream_sequence = 0
        if context is not None:
            current_turn_user_message_id = str(context.get("current_turn_user_message_id") or "").strip() or None
            stream_id = str(context.get("current_response_stream_id") or "").strip() or None
            stream_user_message_id = str(context.get("current_response_stream_user_message_id") or "").strip() or None
            try:
                stream_sequence = int(context.get("current_response_stream_sequence") or 0)
            except Exception:
                stream_sequence = 0
            if not stream_id or (current_turn_user_message_id and stream_user_message_id and current_turn_user_message_id != stream_user_message_id):
                stream_id = str(uuid.uuid4())
                stream_sequence = 0
                context["current_response_stream_id"] = stream_id
                context["current_response_stream_sequence"] = stream_sequence
                context["current_response_stream_started_at"] = time.time()
                context["current_response_stream_session_id"] = session_id
                if current_turn_user_message_id:
                    context["current_response_stream_user_message_id"] = current_turn_user_message_id
                else:
                    context.pop("current_response_stream_user_message_id", None)
        else:
            stream_id = str(uuid.uuid4())
            stream_sequence = 0
        return session, context, stream_id, stream_sequence

    @staticmethod
    def _clear_response_stream_context(context: Optional[Dict[str, Any]]):
        if not isinstance(context, dict):
            return
        for key in (
            "current_response_stream_id",
            "current_response_stream_sequence",
            "current_response_stream_started_at",
            "current_response_stream_session_id",
            "current_response_stream_user_message_id",
            "current_response_stream_completed_at",
        ):
            context.pop(key, None)

    def _build_streamed_response_events(
        self,
        text,
        target,
        is_chunk=False,
        attachments=None,
        model_info=None,
        stream_id=None,
        sequence=None,
    ):
        msg_type = "final_message_chunk" if is_chunk else "assistant_response"
        attachment_list = list(attachments or [])
        stream_id = str(stream_id or "").strip() or str(uuid.uuid4())
        try:
            sequence = int(sequence if sequence is not None else 0)
        except Exception:
            sequence = 0

        response_event = self._normalize_ws_event({
            "type": msg_type,
            "content": text,
            "model_info": model_info,
            "attachments": attachment_list,
            "stream_id": stream_id,
            "sequence": sequence,
        }, session_id=target)

        assistant_chunk_event = None
        next_sequence = sequence + 1
        if is_chunk and text:
            assistant_chunk_event = self._normalize_ws_event({
                "type": "assistant_chunk",
                "content": text,
                "model_info": model_info,
                "attachments": attachment_list,
                "stream_id": stream_id,
                "sequence": next_sequence,
            }, session_id=target)
            next_sequence += 1

        return response_event, assistant_chunk_event, stream_id, next_sequence

    def send_response(self, text, target=None, is_chunk=False, attachments=None, model_info=None, stream_id=None, sequence=None):
        # Input: Text from Kernel
        # Output: Send to specific WebSocket (target=session_id)

        if not target:
            logger.warning("ServerDriver: No target session_id provided for response.")
            return

        # Wait up to 5 seconds for the loop to be captured during startup
        if not self.loop_ready.is_set():
            logger.info("ServerDriver: Waiting for asyncio loop to be ready...")
            self.loop_ready.wait(timeout=5.0)

        if self.loop and not self.loop.is_closed() and target:
            session, context, current_stream_id, current_stream_sequence = self._ensure_response_stream(target)
            if stream_id is None:
                stream_id = current_stream_id
            if sequence is None:
                sequence = current_stream_sequence
            response_event, assistant_chunk_event, stream_id, next_sequence = self._build_streamed_response_events(
                text,
                target,
                is_chunk=is_chunk,
                attachments=attachments,
                model_info=model_info,
                stream_id=stream_id,
                sequence=sequence,
            )
            response_payload = json.dumps(response_event)
            asyncio.run_coroutine_threadsafe(
                self.connection_manager.send_personal_message(response_payload, target), 
                self.loop
            )
            if isinstance(context, dict):
                context["current_response_stream_id"] = stream_id
                context["current_response_stream_sequence"] = next_sequence
            if assistant_chunk_event is not None:
                try:
                    from utils.event_bus import global_event_bus
                    global_event_bus.emit_threadsafe(assistant_chunk_event)
                except Exception as e:
                    logger.debug(f"ServerDriver: Failed to emit assistant_chunk event: {e}")
            return {
                "bridge": "web",
                "status": "sent_to_web_payload",
                "text_sent": bool(text and str(text).strip()),
                "caption_sent": False,
                "sent_attachments": list(attachments or []),
                "attachment_errors": [],
            }
        else:
            logger.error("ServerDriver: Loop not captured or target missing. Cannot send response.")
            return {
                "bridge": "web",
                "status": "error",
                "text_sent": False,
                "caption_sent": False,
                "sent_attachments": [],
                "attachment_errors": [{"bridge": "web", "status": "error", "error": "loop_or_target_missing"}],
            }

    def send_status(self, target, phase, payload=None, model_info=None, stream_id=None, sequence=None):
        """Sends a status update (loader phase)."""
        if not self.loop or self.loop.is_closed() or not target: return
        
        # Backward compatibility: Extract 'label' from payload dict if present
        # Most of our front-ends expect 'message' to be a string.
        display_message = payload
        if isinstance(payload, dict):
            display_message = payload.get('label', payload.get('message', str(payload)))

        # Convert the dictionary to a JSON string for sending over WebSocket
        json_payload = json.dumps(self._normalize_ws_event({
            "type": "status",
            "phase": phase,
            "message": display_message,
            "payload": payload, # Keep full payload for new UI components
            "model_info": model_info,
            **({"stream_id": stream_id} if stream_id else {}),
            **({"sequence": sequence} if sequence is not None else {}),
        }, session_id=target))

        asyncio.run_coroutine_threadsafe(
            self.connection_manager.send_personal_message(json_payload, target), 
            self.loop
        )

    def send_reasoning_chunk(self, target, content, stream_id=None, sequence=None):
        """Sends a reasoning step log."""
        if not self.loop or self.loop.is_closed() or not target: return
        payload = json.dumps(self._normalize_ws_event({
            "type": "reasoning_chunk",
            "content": content,
            **({"stream_id": stream_id} if stream_id else {}),
            **({"sequence": sequence} if sequence is not None else {}),
        }, session_id=target))
        asyncio.run_coroutine_threadsafe(
            self.connection_manager.send_personal_message(payload, target), 
            self.loop
        )

    def send_complete(self, target, stream_id=None, sequence=None):
        """Sends completion signal."""
        if not self.loop or self.loop.is_closed() or not target: return
        session, context = self._get_session_stream_context(target)
        if stream_id is None and isinstance(context, dict):
            stream_id = str(context.get("current_response_stream_id") or "").strip() or None
        if sequence is None and isinstance(context, dict):
            try:
                sequence = int(context.get("current_response_stream_sequence") or 0)
            except Exception:
                sequence = None
        if isinstance(context, dict):
            context["current_response_stream_completed_at"] = time.time()
        payload = json.dumps(self._normalize_ws_event({
            "type": "complete",
            **({"stream_id": stream_id} if stream_id else {}),
            **({"sequence": sequence} if sequence is not None else {}),
        }, session_id=target))
        asyncio.run_coroutine_threadsafe(
            self.connection_manager.send_personal_message(payload, target), 
            self.loop
        )


    def send_thought(self, target, thought):
        """Sends the reasoning process (thought) to the frontend via WebSocket."""
        if not target or not thought:
            return

        if not self.loop_ready.is_set():
            self.loop_ready.wait(timeout=2.0)

        if self.loop and not self.loop.is_closed():
            payload = json.dumps({
                "type": "assistant_thought",
                "content": thought,
                "timestamp": time.time()
            })
            asyncio.run_coroutine_threadsafe(
                self.connection_manager.send_personal_message(payload, target), 
                self.loop
            )

    def send_file(self, target, file_path, caption=None):
        if not target:
            logger.warning("ServerDriver: No target session_id provided for file.")
            return

        if not self.loop_ready.is_set():
            self.loop_ready.wait(timeout=5.0)

        if self.loop and not self.loop.is_closed() and target:
            import os
            filename = os.path.basename(file_path)
            # Use the new secure proxy route for the URL
            # We assume the frontend knows the base API URL or we provide an absolute one
            file_url = f"/api/sessions/{target}/files/{filename}"
            
            response_payload = json.dumps({
                "type": "assistant_response",
                "content": f"[Arquivo: {filename}] {caption if caption else ''}",
                "file": {
                    "name": filename,
                    "url": file_url,
                    "path": file_path, # Keep path for reference
                    "type": "file"
                },
                "timestamp": time.time()
            })
            asyncio.run_coroutine_threadsafe(
                self.connection_manager.send_personal_message(response_payload, target), 
                self.loop
            )
        else:
            logger.error("ServerDriver: Loop not captured or target missing. Cannot send file.")

    def send_voice_event(self, session_id, payload):
        """Standardized method to send Voice Protocol events to the client."""
        if not self.loop or self.loop.is_closed() or not session_id: return
        
        json_payload = json.dumps(payload)
        asyncio.run_coroutine_threadsafe(
            self.connection_manager.send_personal_message(json_payload, session_id), 
            self.loop
        )
