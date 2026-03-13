import base64
import io
import time
import threading
import queue
import re
from typing import Dict, Optional
from utils.logging_config import get_logger
from utils.voice_text import sanitize_tts_text, sanitize_voice_text, normalize_agent_name_for_tts

logger = get_logger("VoiceManager")

class VoiceSessionContext:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.audio_buffer = io.BytesIO()
        self.lock = threading.Lock()
        self.is_processing = False
        self.last_chunk_time = 0.0
        self.turn_id = None
        # VAD State
        self.is_speaking = False
        self.silence_chunks = 0
        self.total_chunks = 0
        self.vad_threshold = 300  # Default base threshold
        self.noise_floor = 150.0   # Adaptive noise floor
        self.is_assistant_speaking = False
        
        # Thinking Interruption State
        self.is_interrupted = False
        self.pending_text = ""
        
        # Streaming TTS Queue
        self.tts_queue = queue.Queue()
        self.tts_worker_thread: Optional[threading.Thread] = None
        self.current_turn_id: Optional[str] = None

        # Incremental STT cache/state
        self.partial_text = ""
        self.partial_last_emit = 0.0
        self.partial_last_attempt = 0.0
        self.partial_inflight = False
        self.partial_seq = 0

class VoiceManager:
    def __init__(self, server_driver):
        self.server_driver = server_driver
        self.kernel = server_driver.kernel
        self.contexts: Dict[str, VoiceSessionContext] = {}
        self.config_manager = getattr(server_driver.kernel, "config_manager", None)
        self.agent_name = ""
        self.agent_spoken_name = ""
        self.vad_silence_chunks = 2
        self.vad_assistant_multiplier = 2.0
        self.vad_threshold_default = 300
        self.endpoint_silence_ms = 900
        self.vad_debug = False
        self.vad_debug_every_chunks = 20
        self._endpoint_watchdog_started = False
        self.partial_stt_enabled = True
        self.partial_stt_interval_ms = 900
        self.partial_stt_min_buffer_ms = 500
        self.partial_stt_window_ms = 3500
        self.partial_stt_min_chars = 4
        
        # Lazy load engines
        self.assistant = None
        self.tts_manager = None

    def _ensure_engines(self):
        if self.assistant: return
        from drivers.interfaces.voice.assistant import Assistant
        from services.tts.manager import TTSManager
        from config.manager import ConfigManager
        
        cfg = self.config_manager or ConfigManager()
        self.config_manager = cfg
        self.tts_manager = TTSManager()
        agent_cfg = cfg.get("agent", {}) if hasattr(cfg, "get") else {}
        self.agent_name = str(agent_cfg.get("agent_name", "Assistant")).strip() or "Assistant"
        self.agent_spoken_name = str(agent_cfg.get("spoken_name", "")).strip()
        voice_cfg = cfg.get("interfaces", {}).get("voice", {}) if hasattr(cfg, "get") else {}
        self.vad_silence_chunks = max(1, int(voice_cfg.get("endpoint_silence_chunks", 2) or 2))
        self.vad_assistant_multiplier = float(voice_cfg.get("vad_assistant_multiplier", 2.0) or 2.0)
        self.vad_threshold_default = int(voice_cfg.get("vad_threshold", 300) or 300)
        self.endpoint_silence_ms = int(voice_cfg.get("endpoint_silence_ms", 900) or 900)
        self.vad_debug = bool(voice_cfg.get("debug_vad", False))
        self.vad_debug_every_chunks = max(1, int(voice_cfg.get("debug_vad_every_chunks", 20) or 20))
        self.partial_stt_enabled = bool(voice_cfg.get("partial_stt_enabled", True))
        self.partial_stt_interval_ms = max(300, int(voice_cfg.get("partial_stt_interval_ms", 900) or 900))
        self.partial_stt_min_buffer_ms = max(200, int(voice_cfg.get("partial_stt_min_buffer_ms", 500) or 500))
        self.partial_stt_window_ms = max(1000, int(voice_cfg.get("partial_stt_window_ms", 3500) or 3500))
        self.partial_stt_min_chars = max(1, int(voice_cfg.get("partial_stt_min_chars", 4) or 4))
        logger.info(
            "Voice config loaded | agent_name='%s' | spoken_name='%s' | vad_threshold=%s | silence_chunks=%s | silence_ms=%s | assistant_mult=%.2f | debug_vad=%s | partial_stt=%s",
            self.agent_name,
            self.agent_spoken_name or "(auto)",
            self.vad_threshold_default,
            self.vad_silence_chunks,
            self.endpoint_silence_ms,
            self.vad_assistant_multiplier,
            self.vad_debug,
            self.partial_stt_enabled,
        )
        self._start_endpoint_watchdog()
        
        # We still need the Assistant driver for backward compatibility/STT initialization 
        # but we prioritize config settings
        stt_cfg = cfg.get_stt_config()
        primary_stt = stt_cfg[0]['provider'] if isinstance(stt_cfg, list) and stt_cfg else 'google'
        
        self.assistant = Assistant(
            voice_recognition_engineering=primary_stt,
            text_to_speech_engineering='google_cloud'
        )
        self.assistant.initialize_voice_recognition_engine()

    def get_context(self, session_id: str) -> VoiceSessionContext:
        if session_id not in self.contexts:
            self.contexts[session_id] = VoiceSessionContext(session_id)
            self.contexts[session_id].vad_threshold = self.vad_threshold_default
        return self.contexts[session_id]

    def handle_chunk(self, session_id: str, b64_data: str):
        self._ensure_engines()
        ctx = self.get_context(session_id)
        try:
            audio_data = base64.b64decode(b64_data)
            with ctx.lock:
                ctx.audio_buffer.write(audio_data)
                ctx.last_chunk_time = time.time()
            
            # Phase 0/1: Intensity tracking starts
            ctx.total_chunks += 1

            # VAD process & Intensity (Now using raw PCM16)
            threading.Thread(target=self._vad_process_pcm, args=(ctx, audio_data), daemon=True).start()
            self._maybe_schedule_partial_stt(ctx)
            
        except Exception as e:
            logger.error(f"Error handling chunk for {session_id}: {e}")

    def _maybe_schedule_partial_stt(self, ctx: VoiceSessionContext):
        if not self.partial_stt_enabled or ctx.is_processing:
            return
        now = time.time()
        interval_sec = float(self.partial_stt_interval_ms) / 1000.0
        with ctx.lock:
            if ctx.partial_inflight:
                return
            if (now - float(ctx.partial_last_attempt or 0.0)) < interval_sec:
                return
            min_bytes = int(16000 * 2 * (float(self.partial_stt_min_buffer_ms) / 1000.0))
            audio_bytes = ctx.audio_buffer.getvalue()
            if len(audio_bytes) < min_bytes:
                return
            window_bytes = int(16000 * 2 * (float(self.partial_stt_window_ms) / 1000.0))
            if window_bytes > 0 and len(audio_bytes) > window_bytes:
                snapshot = audio_bytes[-window_bytes:]
            else:
                snapshot = audio_bytes
            ctx.partial_last_attempt = now
            ctx.partial_inflight = True
            turn_id = ctx.turn_id or f"live_{int(now)}"

        threading.Thread(
            target=self._run_partial_stt,
            args=(ctx, snapshot, turn_id),
            daemon=True,
        ).start()

    def _vad_process_pcm(self, ctx: VoiceSessionContext, pcm_data: bytes):
        """Direct PCM16 VAD logic. No FFmpeg needed."""
        try:
            import numpy as np
            # Convert bytes to int16 array
            samples = np.frombuffer(pcm_data, dtype=np.int16)
            if len(samples) == 0: return

            # Calculate RMS manually
            rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
            
            # Optional VAD telemetry (promoted to INFO when debug_vad=true)
            if self.vad_debug and ctx.total_chunks % self.vad_debug_every_chunks == 0:
                logger.info(
                    "VAD Telemetry | session=%s | rms=%.2f | floor=%.2f | speaking=%s | processing=%s | assistant_speaking=%s",
                    ctx.session_id,
                    rms,
                    ctx.noise_floor,
                    ctx.is_speaking,
                    ctx.is_processing,
                    ctx.is_assistant_speaking,
                )

            # Adaptive Noise Floor: update only with likely ambient chunks
            # to avoid contaminating baseline with user's own speech.
            if not ctx.is_speaking:
                ambient_gate = max(350.0, ctx.noise_floor * 1.6)
                if rms <= ambient_gate:
                    ctx.noise_floor = ctx.noise_floor * 0.92 + rms * 0.08
                else:
                    # Gradual decay if chunk looks like speech burst.
                    ctx.noise_floor = ctx.noise_floor * 0.98
                # Clamp baseline to avoid runaway thresholds.
                min_floor = 80.0
                max_floor = float(max(220, int(self.vad_threshold_default * 0.9)))
                ctx.noise_floor = max(min_floor, min(max_floor, ctx.noise_floor))

            # Broadcast normalized intensity (0.0 to 1.0) for the Orb
            intensity = min(1.0, rms / 8000.0) # Adjusted scale for PCM16
            if intensity > 0.05:
                self.server_driver.send_voice_event(ctx.session_id, {"type": "orb.intensity", "intensity": intensity})

            # Dynamic Threshold: base threshold + adaptive margin.
            margin = 380 if ctx.is_assistant_speaking else 170
            effective_threshold = max(float(self.vad_threshold_default), ctx.noise_floor + margin)
            if self.vad_debug and ctx.total_chunks % self.vad_debug_every_chunks == 0:
                logger.info(
                    "VAD Threshold | session=%s | effective=%.2f | base=%s | margin=%s",
                    ctx.session_id,
                    effective_threshold,
                    self.vad_threshold_default,
                    margin,
                )

            if rms > effective_threshold:
                if not ctx.is_speaking:
                    logger.info(f"VAD: Speech detected (RMS: {rms:.2f} | Floor: {ctx.noise_floor:.2f})")
                    ctx.is_speaking = True
                    
                    # Interruption / Barge-in Logic:
                    # If assistant is SPEAKING or THINKING (processing), we interrupt
                    if ctx.is_assistant_speaking or ctx.is_processing:
                        logger.info(f"Interruption detected: session {ctx.session_id}")
                        
                        # 1. Clear the server-side TTS queue
                        while not ctx.tts_queue.empty():
                            try:
                                ctx.tts_queue.get_nowait()
                                ctx.tts_queue.task_done()
                            except:
                                break
                        
                        # 2. Change current_turn_id to signal worker/stream to stop
                        ctx.current_turn_id = f"interrupted_{int(time.time())}"
                        
                        # 3. Handle Thinking Interruption
                        if ctx.is_processing:
                            ctx.is_interrupted = True
                        
                        # 4. Tell frontend to stop audio playback
                        self.server_driver.send_voice_event(ctx.session_id, {"type": "control.cancel", "reason": "barge_in"})
                        ctx.is_assistant_speaking = False
                    
                    self.server_driver.send_voice_event(ctx.session_id, {"type": "voice.state", "state": "listening"})
                ctx.silence_chunks = 0
            else:
                ctx.silence_chunks += 1
                
            # Endpointing: close turn after configured silence chunks.
            if ctx.is_speaking and ctx.silence_chunks > self.vad_silence_chunks:
                ctx.is_speaking = False
                self.handle_end(ctx.session_id)
                
        except Exception as e:
            logger.debug(f"PCM VAD detail: {e}")

    def _vad_process(self, ctx: VoiceSessionContext, raw_data: bytes):
        """Deprecated WebM VAD. Keeping for legacy fallback if needed."""
        pass

    def _start_endpoint_watchdog(self):
        if self._endpoint_watchdog_started:
            return
        self._endpoint_watchdog_started = True
        threading.Thread(target=self._endpoint_watchdog_loop, daemon=True).start()

    def _endpoint_watchdog_loop(self):
        while True:
            try:
                now = time.time()
                timeout_sec = max(0.3, float(self.endpoint_silence_ms) / 1000.0)
                for sid, ctx in list(self.contexts.items()):
                    if not isinstance(ctx, VoiceSessionContext):
                        continue
                    if ctx.is_speaking and not ctx.is_processing:
                        idle = now - float(ctx.last_chunk_time or 0.0)
                        if idle >= timeout_sec:
                            logger.info(
                                "VAD watchdog forcing endpoint | session=%s | idle_ms=%d | threshold_ms=%d",
                                sid,
                                int(idle * 1000),
                                int(timeout_sec * 1000),
                            )
                            ctx.is_speaking = False
                            self.handle_end(sid)
                time.sleep(0.2)
            except Exception as e:
                logger.debug(f"Endpoint watchdog error: {e}")
                time.sleep(0.5)

    def handle_end(self, session_id: str):
        self._ensure_engines()
        ctx = self.get_context(session_id)
        if ctx.is_processing: return
        ctx.is_processing = True
        threading.Thread(target=self._process_turn, args=(ctx,), daemon=True).start()

    def _run_partial_stt(self, ctx: VoiceSessionContext, pcm_bytes: bytes, turn_id: str):
        try:
            if not pcm_bytes:
                return
            text = self._recognize_pcm_bytes(pcm_bytes)
            text = sanitize_voice_text(text or "")
            if not text or len(text) < self.partial_stt_min_chars:
                return

            should_emit = False
            with ctx.lock:
                if text != ctx.partial_text:
                    ctx.partial_text = text
                    ctx.partial_seq += 1
                    ctx.partial_last_emit = time.time()
                    should_emit = True
                    seq = ctx.partial_seq
                else:
                    seq = ctx.partial_seq

            if should_emit:
                self.server_driver.send_voice_event(ctx.session_id, {
                    "type": "asr.partial",
                    "turnId": turn_id,
                    "text": text,
                    "seq": seq,
                })
        except Exception as e:
            logger.debug(f"Partial STT error ({ctx.session_id}): {e}")
        finally:
            with ctx.lock:
                ctx.partial_inflight = False

    def _process_turn(self, ctx: VoiceSessionContext):
        try:
            self._ensure_engines()
            session_id = ctx.session_id
            ctx.turn_id = f"turn_{int(time.time())}"
            
            logger.info(f"Processing turn {ctx.turn_id} for {session_id} (Buffer: {ctx.audio_buffer.tell()} bytes)")
            self.server_driver.send_voice_event(session_id, {"type": "voice.state", "state": "thinking", "turnId": ctx.turn_id})
            
            with ctx.lock:
                audio_bytes = ctx.audio_buffer.getvalue()
                ctx.audio_buffer = io.BytesIO() # Reset
                cached_partial = (ctx.partial_text or "").strip()
                ctx.partial_text = ""
                ctx.partial_seq = 0

            try:
                text = self._recognize_pcm_bytes(audio_bytes)
            except Exception as e:
                logger.error(f"STT Error: {e}")
                text = None

            if not text:
                if cached_partial:
                    logger.info(
                        "Turn %s using cached partial as final for %s: '%s'",
                        ctx.turn_id,
                        session_id,
                        cached_partial,
                    )
                    text = cached_partial
                else:
                    logger.warning(f"Turn {ctx.turn_id} ended: No speech recognized.")
                    # Reset interruption state if we got nothing
                    ctx.is_interrupted = False
                    self.server_driver.send_voice_event(session_id, {"type": "voice.state", "state": "idle"})
                    ctx.is_processing = False
                    return

            text = sanitize_voice_text(text)
            if not text:
                logger.warning(f"Turn {ctx.turn_id} ended: No speech recognized.")
                # Reset interruption state if we got nothing
                ctx.is_interrupted = False
                self.server_driver.send_voice_event(session_id, {"type": "voice.state", "state": "idle"})
                ctx.is_processing = False
                return

            # Contextual Merge: If we have pending text from an interruption, prepend it
            if ctx.pending_text:
                logger.info(f"Merging pending text: '{ctx.pending_text}' + '{text}'")
                text = f"{ctx.pending_text}. {text}"
                ctx.pending_text = ""

            # Check for Interruption BEFORE sending to kernel
            if ctx.is_interrupted:
                logger.info(f"Turn {ctx.turn_id} interrupted during processing. Stashing text: '{text}'")
                ctx.pending_text = text
                ctx.is_interrupted = False # Reset for next phase
                ctx.is_processing = False
                # Optionally send a 'thinking' reset or keep listening state in UI
                return

            logger.info(f"STT Result for {ctx.turn_id}: '{text}'")
            self.server_driver.send_voice_event(session_id, {"type": "asr.final", "turnId": ctx.turn_id, "text": text})
            
            from core.identity import PrincipalContext
            context = PrincipalContext(
                interface="web", # Use generic 'web' to inherit its 'anyone' mode access
                sender_id=session_id,
                session_id=session_id
            )
            
            class VoiceResponseInterceptor:
                def __init__(self, manager, sid, turn_id):
                    self.manager = manager
                    self.sid = sid
                    self.turn_id = turn_id
                    self.streams_worker_responses = True
                    self.accumulated_text = ""
                    self.sentence_buffer = ""
                    self.in_fenced_code = False
                    self.in_inline_code = False
                    self.fenced_marker_pending = False
                    self.inline_marker_pending = False
                    self.first_response_sent = False
                    self.last_queued_tts = ""

                def _replace_code_tokens_streaming(self, value: str) -> str:
                    text = str(value or "")
                    if not text:
                        return ""
                    out = []
                    i = 0
                    n = len(text)
                    while i < n:
                        # Fenced blocks: ``` ... ``` (stateful across chunks)
                        if text.startswith("```", i):
                            self.in_fenced_code = not self.in_fenced_code
                            if self.in_fenced_code and not self.fenced_marker_pending:
                                out.append(" bloco de código ")
                                self.fenced_marker_pending = True
                            if not self.in_fenced_code:
                                self.fenced_marker_pending = False
                            i += 3
                            # Skip optional fence language token on opening line.
                            if self.in_fenced_code:
                                while i < n and text[i] not in ("\n", "\r"):
                                    i += 1
                            continue

                        if self.in_fenced_code:
                            i += 1
                            continue

                        # Inline code: `...` (stateful across chunks)
                        if text[i] == "`":
                            self.in_inline_code = not self.in_inline_code
                            if self.in_inline_code and not self.inline_marker_pending:
                                out.append(" código ")
                                self.inline_marker_pending = True
                            if not self.in_inline_code:
                                self.inline_marker_pending = False
                            i += 1
                            continue

                        if self.in_inline_code:
                            i += 1
                            continue

                        out.append(text[i])
                        i += 1

                    return "".join(out)
                
                def send_response(self, text, target=None, is_chunk=False, attachments=None):
                    raw_text = str(text or "")
                    if not raw_text.strip():
                        return
                    tts_raw = normalize_agent_name_for_tts(
                        raw_text,
                        self.manager.agent_name,
                        self.manager.agent_spoken_name,
                    )
                    tts_raw = self._replace_code_tokens_streaming(tts_raw)
                    speech_text = (
                        sanitize_tts_text(tts_raw)
                        if self.manager._sanitize_tts_enabled()
                        else tts_raw.strip()
                    )
                    if not speech_text:
                        return
                    
                    self.accumulated_text += raw_text
                    self.sentence_buffer += speech_text
                    self.first_response_sent = True
                    
                    # Detect sentence boundaries: . ? ! \n
                    # We use a simple regex to split and keep the remainder
                    # (?:[.?!]|\n) matches punctuation or newline
                    parts = re.split(r'([.?!]|\n)', self.sentence_buffer)
                    
                    # parts will look like ['Sentence', '.', ' Next sentence', '!', 'Partial']
                    if len(parts) > 2:
                        # We have at least one complete sentence
                        # Re-join segments and punctuation
                        to_queue = ""
                        for i in range(0, len(parts) - 1, 2):
                            to_queue += parts[i] + parts[i+1]
                        
                        self.sentence_buffer = parts[-1] # Keep the partial last segment
                        
                        if to_queue.strip():
                            queued = to_queue.strip()
                            if queued != self.last_queued_tts:
                                self.manager._queue_tts(self.sid, self.turn_id, queued)
                                self.last_queued_tts = queued

                    # Fast-path: work-start ACKs sometimes arrive without punctuation.
                    # To avoid delayed speech, queue first short chunk immediately.
                    if (
                        is_chunk
                        and self.accumulated_text.strip() == raw_text.strip()
                        and not re.search(r"[.?!\n]", speech_text)
                        and 0 < len(speech_text) <= 180
                    ):
                        immediate = speech_text.strip()
                        if immediate and immediate != self.last_queued_tts:
                            self.manager._queue_tts(self.sid, self.turn_id, immediate)
                            self.last_queued_tts = immediate
                            self.sentence_buffer = ""

                    # Standard message for chat history/UI
                    self.manager.server_driver.send_response(raw_text, target=self.sid, is_chunk=is_chunk, attachments=attachments)

                    # Voice protocol events (partial)
                    self.manager.server_driver.send_voice_event(self.sid, {
                        "type": "agent.partial", "turnId": self.turn_id, "text": raw_text
                    })

                def send_complete(self, target=None):
                    # Queue the last bit of text
                    if self.sentence_buffer.strip():
                        self.manager._queue_tts(self.sid, self.turn_id, self.sentence_buffer.strip())
                    
                    # Queue EOF sentinel for this turn
                    self.manager._queue_tts(self.sid, self.turn_id, None)

                    logger.info(f"Interceptor completion for turn {self.turn_id}")
                    self.manager.server_driver.send_voice_event(self.sid, {
                        "type": "agent.final", "turnId": self.turn_id, "text": self.accumulated_text
                    })

                def send_status(self, target, phase, payload=None):
                    self.manager.server_driver.send_status(target, phase, payload)

                def send_reasoning_chunk(self, content):
                    # Mark capability so Kernel/EventConsumer doesn't replay final result.
                    return None

                def get_capabilities(self):
                    return {
                        "markdown": True,
                        "rich_media": True,
                        "voice_only": False,
                        "streaming": True,
                    }

            interceptor = VoiceResponseInterceptor(self, session_id, ctx.turn_id)
            self.kernel.process_input(
                text,
                interceptor,
                user_id=session_id,
                user_data={
                    "interaction_mode": "voice",
                    "is_voice_interaction": True,
                    "channel": "Voice",
                },
                context=context,
            )

        except Exception as e:
            logger.error(f"Error in _process_turn: {e}")
        finally:
            ctx.is_processing = False

    def _recognize_pcm_bytes(self, pcm_bytes: bytes) -> str:
        if not pcm_bytes:
            return ""
        import wave
        import speech_recognition as sr
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2) # PCM16
            wav_file.setframerate(16000)
            wav_file.writeframes(pcm_bytes)
        wav_buffer.seek(0)
        r = sr.Recognizer()
        with sr.AudioFile(wav_buffer) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language='pt-BR')
        return text

    def _recognize_file_pcm(self, wav_path):
        # Backward-compatible helper for existing callers.
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language='pt-BR')
        return text

    def _recognize_file(self, path):
        """Deprecated WebM recognizer."""
        pass

    def _queue_tts(self, session_id, turn_id, text):
        ctx = self.get_context(session_id)
        ctx.current_turn_id = turn_id
        ctx.tts_queue.put((turn_id, text))
        
        # Start worker if not active
        if not ctx.tts_worker_thread or not ctx.tts_worker_thread.is_alive():
            ctx.tts_worker_thread = threading.Thread(
                target=self._tts_worker, 
                args=(session_id,), 
                daemon=True
            )
            ctx.tts_worker_thread.start()

    def _tts_worker(self, session_id):
        ctx = self.get_context(session_id)
        logger.info(f"TTS Worker started for session {session_id}")
        
        while session_id in self.contexts:
            try:
                # Wait for next segment
                turn_id, text = ctx.tts_queue.get(timeout=10) # 10s idle timeout
                
                if text is None:
                    # EOF sentinel for turn
                    logger.info(f"TTS Turn {turn_id} complete (Queue EOF)")
                    ctx.tts_queue.task_done()
                    # If no more items and EOF reached, we can signal idle
                    if ctx.tts_queue.empty():
                        ctx.is_assistant_speaking = False
                        self.server_driver.send_voice_event(session_id, {"type": "voice.state", "state": "listening", "turnId": turn_id})
                    continue

                # Process segment
                ctx.is_assistant_speaking = True
                self._speak_segment(session_id, turn_id, text)
                ctx.tts_queue.task_done()
                
            except queue.Empty:
                # If idle for too long, exit worker to save resources
                logger.info(f"TTS Worker for {session_id} stopping (Idle)")
                ctx.is_assistant_speaking = False
                break
            except Exception as e:
                logger.error(f"TTS Worker Error for {session_id}: {e}")
                break

    def _speak_segment(self, session_id, turn_id, text):
        ctx = self.get_context(session_id)
        
        # Check if we should still be speaking this turn (barge-in might clear it)
        if ctx.current_turn_id != turn_id:
            logger.info(f"Skipping stale TTS segment for {turn_id}")
            return

        # No local flag management, managed by worker loop
        tts_raw = normalize_agent_name_for_tts(
            str(text or ""),
            self.agent_name,
            self.agent_spoken_name,
        )
        speak_text = sanitize_tts_text(tts_raw) if self._sanitize_tts_enabled() else tts_raw.strip()
        
        try:
            if not speak_text:
                return

            self.server_driver.send_voice_event(session_id, {"type": "tts.start", "turnId": turn_id, "text": speak_text})
            
            logger.info(f"Generating TTS segment for turn {turn_id}: {speak_text[:30]}...")
            audio_content = self.tts_manager.generate(speak_text)
            
            if audio_content:
                chunk_size = 32 * 1024
                for i, offset in enumerate(range(0, len(audio_content), chunk_size)):
                    # Check for barge-in interruption during stream
                    if ctx.current_turn_id != turn_id:
                        logger.info(f"Barge-in: Interrupting TTS stream for {turn_id}")
                        break

                    chunk = audio_content[offset : offset + chunk_size]
                    audio_b64 = base64.b64encode(chunk).decode('utf-8')
                    self.server_driver.send_voice_event(session_id, {
                        "type": "tts.chunk", "turnId": turn_id, "seq": i + 1, "b64": audio_b64
                    })
                    time.sleep(0.01)
                
            self.server_driver.send_voice_event(session_id, {"type": "tts.end", "turnId": turn_id})
        except Exception as e:
            logger.error(f"TTS Segment Error: {e}")
        finally:
            pass # Flag managed by worker loop

    def _sanitize_tts_enabled(self) -> bool:
        try:
            if not self.config_manager:
                return True
            return bool(
                self.config_manager.get("interfaces", {}).get("voice", {}).get("sanitize_tts_text", True)
            )
        except Exception:
            return True
