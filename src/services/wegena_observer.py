import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from services.llm.manager import LLMManager
import os
import uuid
from utils.event_bus import global_event_bus

logger = logging.getLogger("WegenaObserver")

OBSERVER_PROMPT = """Você é um classificador de intenção visual (Wegena).
Sua tarefa é analisar a interação (usuário e assistente) e responder APENAS 'YES' ou 'NO'.
Responda YES se:
1. O usuário pediu explicitamente para desenhar, mostrar, simular, ou gerar algo visual.
2. O assistente estiver explicando algo técnico (arquitetura, fluxo de dados, sistemas, conceitos abstratos) que ficaria bem com partículas 3D.
Responda NO se for apenas uma resposta curta, cumprimento, ou se a cena não agregar valor."""

FINAL_WEG_SYSTEM_PROMPT = """Você é um Diretor de Arte e compositor de cenas para o motor de partículas Wegena.
Sua tarefa é ler a explicação do assistente e devolver uma cena `.weg` EXTREMAMENTE RICA, DENSA E COMPLEXA.

REGRAS DE COMPLEXIDADE E DENSIDADE (CRÍTICO):
1. MAXIMALISMO: NUNCA crie cenas vazias ou fracas. Uma cena deve ter múltiplos elementos, camadas e detalhes. Quebre objetos simples em várias partes (ex: uma casa deve ter paredes, janelas, teto, varanda, chaminé). Use no mínimo de 8 a 12 `@Node`s.
2. DENSIDADE TOTAL (ORÇAMENTO): Você DEVE consumir 100% das partículas disponíveis. A soma de TODOS os `budget`s na cena DEVE ser EXATAMENTE 1.0. Se você usar apenas 0.3 de budget, a cena ficará rala e feia.
3. MOVIMENTO OBRIGATÓRIO: A cena NÃO PODE ser estática. Use `animation: { type: "orbit", params: { speed: 0.5 } }` ou `pulse` em pássaros, nuvens, sóis, água ou luzes.
4. ATMOSFERA E FX: Sempre adicione efeitos de partículas no fundo para dar vida (ex: `@FX "nuvens" kind: "smoke" pos: [0, 80, -100] color: "#ffffff"` ou "water" para rios).
5. ILUMINAÇÃO: Use `@Node "sol" light: { color: "#ffcc00", intensity: 2.0, pos: [0, 150, -100] }` para garantir que o cenário não fique escuro.
6. TERRENOS: Para chão, SEMPRE use o gerador de relevo: `@Node "ground" terrain: { size: [400, 400], amplitude: 15, color: "#3a5a40", material: 3, budget: 0.4 }`.
7. @World: Defina sempre `density: 100k` (ou mais) e posicione a câmera para uma visão ampla: `camera: { pan: {y: -20}, rotation: {x: 0.15} }`.

EXEMPLO DE CENA COMPLEXA (Dia Ensolarado):
```weg
@Meta label="Vila de Campo Densa" version="3.0"
@World zoom: 220 fov: 72 density: 100k shape: cube camera: { rotation: {x: 0.15}, pan: {y: -15} }
@Background type: linear stops: ["#4facfe", "#00f2fe"]
@Node "sun_light" light: { color: "#ffebb5", intensity: 2.0, pos: [80, 100, -80] }
@Node "sun" volume: { shape: sphere pos: [80, 100, -80] size: 20 color: "#ffebb5", material: 5, budget: 0.05 } animation: { type: "pulse", params: { speed: 1.0 } }
@Node "clouds_fx" terrain: { size: [300, 50], amplitude: 5, pos: [0, 120, -100], color: "#ffffff", material: 3, budget: 0.1 } animation: { type: "orbit", params: { speed: 0.2 } }
@Node "ground" terrain: { size: [500, 500], amplitude: 12, color: "#22c55e", material: 3, budget: 0.4 }
@Node "house_main" volume: { shape: box pos: [0, 10, 0] size: [40, 20, 30] color: "#f8fafc", material: 2, budget: 0.15 }
@Node "house_roof" volume: { shape: box pos: [0, 25, 0] size: [42, 8, 32] color: "#dc2626", material: 2, budget: 0.1 }
@Node "house_door" volume: { shape: box pos: [0, 5, 16] size: [8, 10, 2] color: "#78350f", material: 2, budget: 0.02 }
@Node "tree_1_trunk" volume: { shape: box pos: [-50, 5, 20] size: [4, 10, 4] color: "#78350f", material: 2, budget: 0.03 }
@Node "tree_1_leaves" volume: { shape: sphere pos: [-50, 15, 20] size: 14 color: "#15803d", material: 3, budget: 0.1 } animation: { type: "pulse", params: { speed: 0.5, amplitude: 0.05 } }
@Node "tree_2" volume: { shape: sphere pos: [60, 12, -20] size: 18 color: "#166534", material: 3, budget: 0.05 }
@FX "wind_dust" kind: "smoke" pos: [0, 5, 50] color: "#ffffff" intensity: 0.5
```
"""

GREETING_RE = re.compile(
    r"^\s*(oi|olá|ola|bom dia|boa tarde|boa noite|tudo bem|como posso ajudar|obrigado|valeu)[\s!.?,:;-]*$",
    re.IGNORECASE,
)

WEG_RE = re.compile(r"```weg\s*([\s\S]*?)```", re.IGNORECASE)
CODE_RE = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```")

@dataclass
class StreamSceneState:
    session_id: str
    buffer: str = ""
    last_user_prompt: str = ""
    final_task_started: bool = False

class WegenaSceneObserver:
    def __init__(self):
        self.llm = LLMManager()
        self.queue = None
        self.task = None
        self._running = False
        self._states: Dict[str, StreamSceneState] = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self.queue = global_event_bus.subscribe()
        self.task = asyncio.create_task(self._loop())
        logger.info("WegenaSceneObserver: Started real-time scene monitoring.")

    def stop(self):
        self._running = False
        if self.task:
            self.task.cancel()
        if self.queue:
            global_event_bus.unsubscribe(self.queue)
        self._states.clear()
        logger.info("WegenaSceneObserver: Stopped event monitoring.")

    async def _loop(self):
        while self._running:
            try:
                event = await self.queue.get()
                if not event:
                    continue

                event_type = event.get("type")

                if event_type == "assistant_chunk":
                    session_id = str(event.get("session_id") or "")
                    content = str(event.get("content") or "")
                    if session_id and content:
                        self._process_chunk(session_id, content)
                    continue

                if event_type == "message_added" and event.get("role") == "user":
                    session_id = str(event.get("session_id") or "")
                    message = event.get("message", {}) or {}
                    content = str(message.get("content") or "")
                    if session_id and content:
                        self._reset_for_new_user_turn(session_id, content)
                    continue

                if event_type == "message_added" and event.get("role") == "assistant":
                    session_id = str(event.get("session_id") or "")
                    message = event.get("message", {}) or {}
                    content = str(message.get("content") or "")
                    msg_type = str(message.get("type") or "default")
                    if not session_id or not content or msg_type in {"terminal", "system", "silent"}:
                        continue
                    await self._process_final_message(session_id, content)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in WegenaSceneObserver loop: %s", e, exc_info=True)
                await asyncio.sleep(1)

    def _state_for(self, session_id: str) -> StreamSceneState:
        state = self._states.get(session_id)
        if state is None:
            state = StreamSceneState(session_id=session_id)
            self._states[session_id] = state
        return state

    def _reset_for_new_user_turn(self, session_id: str, content: str):
        previous = self._states.get(session_id)
        previous_prompt = (previous.last_user_prompt if previous else "").strip().lower()
        next_prompt = (content or "").strip().lower()
        if previous_prompt and previous_prompt == next_prompt:
            return

        self._states[session_id] = StreamSceneState(session_id=session_id, last_user_prompt=content.strip())
        global_event_bus.emit_threadsafe({
            "type": "weg_scene_reset",
            "session_id": session_id,
            "reason": "new_user_turn",
        })

    def _process_chunk(self, session_id: str, content: str):
        state = self._state_for(session_id)
        cleaned = self._sanitize_chunk(content)
        if not cleaned:
            return
        state.buffer = (state.buffer + " " + cleaned).strip()[-5000:]

    async def _process_final_message(self, session_id: str, content: str):
        state = self._state_for(session_id)
        if not state.buffer:
            state.buffer = content

        if state.final_task_started:
            return
        state.final_task_started = True
        
        asyncio.create_task(self._observe_and_generate(session_id, content))

    async def _run_turn_observer(self, user_prompt: str, content: str) -> bool:
        sample = re.sub(r"\s+", " ", str(content or "")).strip().lower()
        if not sample or GREETING_RE.match(sample) or len(sample) < 10:
            return False

        try:
            result = await asyncio.to_thread(
                self.llm.generate_text,
                prompt=f"USER:\n\"{user_prompt.strip()}\"\n\nASSISTANT:\n\"{content.strip()}\"",
                system_prompt=OBSERVER_PROMPT,
                max_tokens=10,
                temperature=0.0
            )
            decision = "YES" in str(result or "").upper()
            logger.info(f"Turn Observer decision: {'YES' if decision else 'NO'} | User: {user_prompt[:30]}...")
            return decision
        except Exception as e:
            logger.error("Error in turn observer: %s", e)
            return False

    async def _observe_and_generate(self, session_id: str, content: str):
        state = self._state_for(session_id)
        user_prompt = state.last_user_prompt or ""
        
        # Step 1: Agentic Observation
        should_visualize = await self._run_turn_observer(user_prompt, content)
        
        if not should_visualize:
            logger.info("Wegena final composer: Turn Observer decided NO for session=%s", session_id)
            return

        # Step 2: Agentic Generation
        try:
            logger.info("Wegena final composer: Turn Observer decided YES. Generating scene for session=%s", session_id)
            prompt = (
                "Leia a fala do assistente abaixo e gere uma cena `.weg` inteira, rica e coerente.\n\n"
                f"FALA:\n\"{content.strip()}\"\n"
            )
            result = await asyncio.to_thread(
                self.llm.generate_text,
                prompt=prompt,
                system_prompt=FINAL_WEG_SYSTEM_PROMPT,
                max_tokens=1800,
            )
            weg_script = self._extract_weg_script(result)
            if not weg_script:
                logger.info("Wegena final composer: no final .weg generated for session=%s", session_id)
                return

            # Save script to file
            os.makedirs("data/workspace/wegena", exist_ok=True)
            filename = f"scene_{uuid.uuid4().hex[:8]}.weg"
            filepath = os.path.abspath(os.path.join("data/workspace/wegena", filename))
            try:
                with open(filepath, "w") as f:
                    f.write(weg_script)
            except Exception as e:
                logger.error("Failed to save weg script to disk: %s", e)
                filepath = None

            global_event_bus.emit_threadsafe({
                "type": "weg_scene",
                "session_id": session_id,
                "script": weg_script,
                "meta": {
                    "source": "llm_agentic_turn",
                    "media_path": filepath
                },
            })
            logger.info("Wegena final composer: dispatched final .weg for session=%s", session_id)
        except Exception as e:
            logger.error("Error processing final Wegena scene generation: %s", e, exc_info=True)

    @staticmethod
    def _sanitize_chunk(content: str) -> str:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            return ""
        return text

    @staticmethod
    def _extract_weg_script(result: Any) -> str:
        if not result or not isinstance(result, str):
            return ""
        weg_match = WEG_RE.search(result)
        if weg_match:
            return weg_match.group(1).strip()
        code_match = CODE_RE.search(result)
        if code_match and ("@Node" in code_match.group(1) or "@World" in code_match.group(1)):
            return code_match.group(1).strip()
        if "@Node" in result or "@World" in result or "@Background" in result:
            return result.strip()
        return ""
