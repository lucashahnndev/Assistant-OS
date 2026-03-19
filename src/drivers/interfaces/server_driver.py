import threading
import uvicorn
import asyncio
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict
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
    # ... (no changes to ConnectionManager)
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"Client connected: {session_id}. Total: {len(self.active_connections)}")

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info(f"Client disconnected: {session_id}")

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

    async def send_personal_message(self, message: str, session_id: str):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to {session_id}: {e}")

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

    def _setup_extra_routes(self):
        @self.app.on_event("startup")
        async def startup_event():
            self.loop = asyncio.get_running_loop()
            self.loop_ready.set()
            logger.info("ServerDriver: Captured asyncio loop and set ready event.")
            
            # Bridge global_event_bus to WebSockets
            from utils.event_bus import global_event_bus
            global_event_bus.set_loop(self.loop)
            
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
                        payload = json.dumps(event)
                        
                        # List-affecting events should be broadcasted so ALL connected clients
                        # (even if on different active sessions) see the updates in their sidebar.
                        if event.get("type") in ["session_updated", "unread_count_updated", "message_added"]:
                            await self.connection_manager.broadcast(payload)
                        elif target:
                             await self.connection_manager.send_personal_message(payload, target)
                        else:
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

                    # Process in background thread to avoid blocking WebSocket loop
                    threading.Thread(
                        target=self._process_message,
                        args=(content, session_id, attachments, user_data, sender_id, sender_name),
                    ).start()
                    
            except WebSocketDisconnect:
                self.connection_manager.disconnect(session_id)
            except Exception as e:
                logger.error(f"WebSocket Error: {e}")
                self.connection_manager.disconnect(session_id)
 
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
         self.kernel.process_input(
             message,
             self,
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

    def send_response(self, text, target=None, is_chunk=False, attachments=None):
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
            # Prepare JSON response
            # Standardized message types for the new Portal UI
            msg_type = "final_message_chunk" if is_chunk else "assistant_response"
            
            response_payload = json.dumps({
                "type": msg_type,
                "content": text,
                "timestamp": time.time(),
                "attachments": attachments
            })
            asyncio.run_coroutine_threadsafe(
                self.connection_manager.send_personal_message(response_payload, target), 
                self.loop
            )
        else:
            logger.error("ServerDriver: Loop not captured or target missing. Cannot send response.")

    def send_status(self, target, phase, payload=None):
        """Sends a status update (loader phase)."""
        if not self.loop or self.loop.is_closed() or not target: return
        
        # Backward compatibility: Extract 'label' from payload dict if present
        # Most of our front-ends expect 'message' to be a string.
        display_message = payload
        if isinstance(payload, dict):
            display_message = payload.get('label', payload.get('message', str(payload)))

        # Convert the dictionary to a JSON string for sending over WebSocket
        json_payload = json.dumps({
            "type": "status",
            "phase": phase,
            "message": display_message,
            "payload": payload, # Keep full payload for new UI components
            "timestamp": time.time()
        })

        asyncio.run_coroutine_threadsafe(
            self.connection_manager.send_personal_message(json_payload, target), 
            self.loop
        )

    def send_reasoning_chunk(self, target, content):
        """Sends a reasoning step log."""
        if not self.loop or self.loop.is_closed() or not target: return
        payload = json.dumps({
            "type": "reasoning_chunk",
            "content": content,
            "timestamp": time.time()
        })
        asyncio.run_coroutine_threadsafe(
            self.connection_manager.send_personal_message(payload, target), 
            self.loop
        )

    def send_complete(self, target):
        """Sends completion signal."""
        if not self.loop or self.loop.is_closed() or not target: return
        payload = json.dumps({
            "type": "complete",
            "timestamp": time.time()
        })
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
