import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from services.llm.manager import LLMManager
from utils.event_bus import global_event_bus

logger = logging.getLogger("WegenaObserver")

FINAL_WEG_SYSTEM_PROMPT = """Você é um compositor silencioso de cenas para o motor Wegena.
Sua única tarefa é ler a explicação do assistente e devolver uma cena `.weg` visualmente rica que ilustre o conceito.

REGRAS:
1. Nunca converse. Nunca explique. Nunca escreva texto fora do bloco ```weg.
2. Se a fala for apenas social, vazia ou sem conteúdo visualizável, responda exatamente: Não visualizar
3. Se visualizar, produza uma cena rica, coerente e legível para um LLM local de 14B. Prefira clareza sem exagerar na complexidade sintática.
4. Use a DSL real do Wegena: `@Meta`, `@World`, `@Background`, `@Node`, e as NOVAS FUNCIONALIDADES:
   - Efeitos especiais (FX): `@FX "name" kind: "burst"`, `kind: "smoke"`, `kind: "fire"`, `kind: "exhaust"`, ou `kind: "water"`.
   - Inserção em Massa: `[Nodes: name, kind, pos, size, color]` para tabelas CSV.
   - Lógica Procedural: `@Loop count: N var: v`, `@End`, `@Var name = value` e `@If condition`.
5. Sempre defina fundo e câmera.
6. Para explicações técnicas, use de 6 a 14 nós nomeados relevantes, priorizando a identidade estável dos nós principais.
7. Preserve topologia espacial clara: origem, intermediários, destino, detalhes atmosféricos.
8. Distinga Fogo: use `kind: "fire"` para chama ascendente (fogueira, tocha) e `kind: "exhaust"` para propulsão (foguetes, turbinas).

EXEMPLO:
```weg
@Meta label="Fluxo Distribuído" version="5.0.0"
@World zoom: 165 fov: 72 density: 42k size: 1.05 shape: point
@Background type: linear stops: ["#02040a", "#10233d"]
@Node "server_origin" volume: { shape: box pos: [-52, 0, 0] size: [18, 26, 18] color: "#4cc9f0" material: 2 count: 8200 }
@Node "gateway_hub" volume: { shape: sphere pos: [0, 6, 0] size: 16 color: "#a855f7" material: 5 count: 6800 }
@Node "server_target" volume: { shape: box pos: [52, 0, 0] size: [18, 26, 18] color: "#22c55e" material: 2 count: 8200 }
@FX "packet_burst" kind: "burst" pos: [0, 6, 0] color: "#ffffff" intensity: 2
@FX "exhaust_main" kind: "exhaust" pos: [-52, -15, 0] color: "#ff8800"
```
"""

VISUAL_KEYWORDS = (
    "servid", "dados", "pacote", "rede", "network", "api", "request", "response",
    "gateway", "router", "database", "banco", "cache", "fila", "queue", "cloud",
    "nuvem", "chuva", "vapor", "pipeline", "fluxo", "transmiss", "sincron", "replica",
    "telemet", "monitor", "process", "nó", "node", "latência", "stream"
)

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
    template_id: Optional[str] = None
    initialized: bool = False
    emitted_nodes: Set[str] = field(default_factory=set)
    scene_nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    env_state: Dict[str, Any] = field(default_factory=dict)
    last_template_emit_at: float = 0.0
    last_chunk_at: float = 0.0
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
                if event_type == "assistant_visual_intent":
                    session_id = str(event.get("session_id") or "")
                    payload = event.get("payload", {}) or {}
                    if session_id:
                        self._process_visual_intent(session_id, payload)
                    continue

                if event_type == "assistant_chunk":
                    session_id = str(event.get("session_id") or "")
                    content = str(event.get("content") or "")
                    if session_id and content:
                        await self._process_chunk(session_id, content)
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

        state = StreamSceneState(session_id=session_id, last_user_prompt=content.strip())
        self._states[session_id] = state
        global_event_bus.emit_threadsafe({
            "type": "weg_scene_reset",
            "session_id": session_id,
            "reason": "new_user_turn",
        })

    def _reset_stream_state(self, state: StreamSceneState, *, keep_user_prompt: bool, emit_reset: bool):
        user_prompt = state.last_user_prompt if keep_user_prompt else ""
        session_id = state.session_id
        self._states[session_id] = StreamSceneState(session_id=session_id, last_user_prompt=user_prompt)
        if emit_reset:
            global_event_bus.emit_threadsafe({
                "type": "weg_scene_reset",
                "session_id": session_id,
                "reason": "template_shift",
            })

    def _process_visual_intent(self, session_id: str, payload: Dict[str, Any]):
        state = self._state_for(session_id)
        mode = str(payload.get("mode") or "").strip().lower()
        if mode not in {"data_flow", "cloud_rain", "neural_mesh", "concept_orbit"}:
            mode = "concept_orbit"
        intent = str(payload.get("intent") or "").strip()
        background_policy = str(payload.get("background_policy") or "adaptive").strip().lower()

        if state.template_id and state.template_id != mode:
            self._reset_stream_state(state, keep_user_prompt=True, emit_reset=True)
            state = self._state_for(session_id)

        if intent:
            state.buffer = (state.buffer + " " + intent).strip()[-5000:]
        state.template_id = mode
        if not state.initialized:
            self._emit_scene_init(session_id, mode)
            state.initialized = True

        elements = self._build_template_elements(mode, state.buffer or intent or mode)
        for element in elements:
            name = str(element.get("name") or "")
            if not name:
                continue
            previous = state.scene_nodes.get(name)
            if previous is not None and not self._element_changed(previous, element):
                continue
            self._emit_scene_patch(session_id, element, mode)
            state.emitted_nodes.add(name)
            state.scene_nodes[name] = self._clone_element(element)

        env_update = self._build_env_update(mode, f"{background_policy} {state.buffer or intent or mode}")
        if env_update and self._env_changed(state.env_state, env_update):
            self._emit_scene_env(session_id, env_update, mode)
            state.env_state = self._deep_merge_dicts(state.env_state, env_update)

    async def _process_chunk(self, session_id: str, content: str):
        state = self._state_for(session_id)
        cleaned = self._sanitize_chunk(content)
        if not cleaned:
            return

        state.buffer = (state.buffer + " " + cleaned).strip()[-5000:]
        state.last_chunk_at = time.monotonic()

        if not self._should_visualize_fast(state.buffer):
            return

        template_id = self._choose_template(state.buffer)
        if not template_id:
            return

        if state.template_id and state.template_id != template_id:
            self._reset_stream_state(state, keep_user_prompt=True, emit_reset=True)
            state = self._state_for(session_id)

        state.template_id = template_id
        if not state.initialized:
            self._emit_scene_init(session_id, template_id)
            state.initialized = True

        elements = self._build_template_elements(template_id, state.buffer)
        current_names = {str(element.get("name") or "") for element in elements if str(element.get("name") or "")}
        changed_now = 0
        for element in elements:
            name = str(element.get("name") or "")
            if not name:
                continue
            previous = state.scene_nodes.get(name)
            if previous is not None and not self._element_changed(previous, element):
                continue
            self._emit_scene_patch(session_id, element, template_id)
            state.emitted_nodes.add(name)
            state.scene_nodes[name] = self._clone_element(element)
            changed_now += 1

        if changed_now:
            state.last_template_emit_at = time.monotonic()

        stale_names = [name for name in list(state.scene_nodes.keys()) if name not in current_names]
        for stale_name in stale_names:
            self._emit_scene_remove(session_id, stale_name, template_id)
            state.scene_nodes.pop(stale_name, None)
            state.emitted_nodes.discard(stale_name)

        env_update = self._build_env_update(template_id, state.buffer)
        if env_update and self._env_changed(state.env_state, env_update):
            self._emit_scene_env(session_id, env_update, template_id)
            state.env_state = self._deep_merge_dicts(state.env_state, env_update)

    async def _process_final_message(self, session_id: str, content: str):
        state = self._state_for(session_id)
        if not state.buffer:
            state.buffer = content

        if self._should_visualize_fast(content) and not state.initialized:
            template_id = self._choose_template(content)
            if template_id:
                state.template_id = template_id
                self._emit_scene_init(session_id, template_id)
                state.initialized = True
                for element in self._build_template_elements(template_id, content):
                    name = str(element.get("name") or "")
                    if name and name not in state.emitted_nodes:
                        self._emit_scene_patch(session_id, element, template_id)
                        state.emitted_nodes.add(name)
                        state.scene_nodes[name] = self._clone_element(element)

        if state.final_task_started:
            return
        state.final_task_started = True
        asyncio.create_task(self._process_final_weg(session_id, content))

    async def _process_final_weg(self, session_id: str, content: str):
        try:
            logger.info("Wegena final composer: analyzing session=%s preview=%s", session_id, content[:120])
            state = self._state_for(session_id)
            scaffold_summary = self._summarize_state_for_prompt(state)
            prompt = (
                "Leia a fala do assistente abaixo e gere uma cena `.weg` final, rica e coerente.\n\n"
                f"SCAFFOLD ATUAL:\n{scaffold_summary}\n\n"
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

            global_event_bus.emit_threadsafe({
                "type": "weg_scene",
                "session_id": session_id,
                "script": weg_script,
                "meta": {
                    "source": "llm_final",
                    "template": state.template_id,
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
    def _should_visualize_fast(text: str) -> bool:
        sample = re.sub(r"\s+", " ", str(text or "")).strip().lower()
        if not sample or GREETING_RE.match(sample):
            return False
        if len(sample) < 20:
            return False
        return any(token in sample for token in VISUAL_KEYWORDS)

    @staticmethod
    def _choose_template(text: str) -> Optional[str]:
        lowered = str(text or "").lower()
        if any(word in lowered for word in ("nuvem", "chuva", "vapor", "condens", "gotas", "tempest")):
            return "cloud_rain"
        if any(word in lowered for word in ("server", "servid", "dados", "pacote", "api", "gateway", "database", "cache", "fila", "request", "response", "rede", "pipeline", "fluxo")):
            return "data_flow"
        if any(word in lowered for word in ("orb", "núcleo", "neural", "sinapse", "atlas")):
            return "neural_mesh"
        return "concept_orbit"

    def _emit_scene_init(self, session_id: str, template_id: str):
        global_event_bus.emit_threadsafe({
            "type": "weg_scene_init",
            "session_id": session_id,
            "config": self._template_config(template_id),
            "meta": {"template": template_id, "source": "scaffold"},
        })

    def _emit_scene_patch(self, session_id: str, element: Dict[str, Any], template_id: str):
        global_event_bus.emit_threadsafe({
            "type": "weg_scene_patch",
            "session_id": session_id,
            "element": element,
            "meta": {"template": template_id, "source": "scaffold"},
        })

    def _emit_scene_remove(self, session_id: str, name: str, template_id: str):
        global_event_bus.emit_threadsafe({
            "type": "weg_scene_remove",
            "session_id": session_id,
            "name": name,
            "meta": {"template": template_id, "source": "scaffold"},
        })

    def _emit_scene_env(self, session_id: str, env: Dict[str, Any], template_id: str):
        global_event_bus.emit_threadsafe({
            "type": "weg_scene_env",
            "session_id": session_id,
            "env": env,
            "meta": {"template": template_id, "source": "scaffold"},
        })

    @staticmethod
    def _clone_element(element: Dict[str, Any]) -> Dict[str, Any]:
        import copy
        return copy.deepcopy(element)

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: WegenaSceneObserver._normalize_value(value[k]) for k in sorted(value.keys())}
        if isinstance(value, list):
            return [WegenaSceneObserver._normalize_value(v) for v in value]
        return value

    @classmethod
    def _element_changed(cls, previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
        return cls._normalize_value(previous) != cls._normalize_value(current)

    @classmethod
    def _env_changed(cls, previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
        merged = cls._deep_merge_dicts(previous, current)
        return cls._normalize_value(previous) != cls._normalize_value(merged)

    @staticmethod
    def _deep_merge_dicts(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        merged: Dict[str, Any] = dict(base or {})
        for key, value in (update or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = WegenaSceneObserver._deep_merge_dicts(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _summarize_state_for_prompt(state: StreamSceneState) -> str:
        if not state.scene_nodes:
            return "nenhum scaffold emitido"
        names = ", ".join(sorted(state.scene_nodes.keys())[:16])
        env_keys = ", ".join(sorted(state.env_state.keys())) if state.env_state else "nenhum"
        template = state.template_id or "desconhecido"
        return f"template={template}; nodes={names}; env={env_keys}"

    @staticmethod
    def _template_config(template_id: str) -> Dict[str, Any]:
        configs = {
            "data_flow": {
                "particles": {"density": 42000, "size": 0.95, "material": 0},
                "env": {
                    "background": {
                        "type": "linear",
                        "stops": ["#030611", "#10243b"],
                    }
                },
                "camera": {"zoom": 170, "rotation": {"x": 0.18, "y": -0.32}},
            },
            "cloud_rain": {
                "particles": {"density": 44000, "size": 1.0, "material": 4},
                "env": {
                    "background": {
                        "type": "linear",
                        "stops": ["#091525", "#284765"],
                    }
                },
                "camera": {"zoom": 168, "rotation": {"x": 0.12, "y": -0.1}},
            },
            "neural_mesh": {
                "particles": {"density": 48000, "size": 0.9, "material": 4},
                "env": {
                    "background": {
                        "type": "radial",
                        "stops": [
                            {"color": "#030615", "pos": 0},
                            {"color": "#0b1730", "pos": 55},
                            {"color": "#000104", "pos": 100},
                        ],
                    }
                },
                "camera": {"zoom": 180, "rotation": {"x": 0.22, "y": -0.42}},
            },
            "concept_orbit": {
                "particles": {"density": 36000, "size": 0.95, "material": 0},
                "env": {
                    "background": {
                        "type": "linear",
                        "stops": ["#04050a", "#101426"],
                    }
                },
                "camera": {"zoom": 175, "rotation": {"x": 0.18, "y": -0.24}},
            },
        }
        return configs.get(template_id, configs["concept_orbit"])

    def _build_template_elements(self, template_id: str, text: str) -> List[Dict[str, Any]]:
        lowered = str(text or "").lower()
        if template_id == "data_flow":
            return self._build_data_flow_elements(lowered)
        if template_id == "cloud_rain":
            return self._build_cloud_rain_elements(lowered)
        if template_id == "neural_mesh":
            return self._build_neural_mesh_elements(lowered)
        return self._build_concept_orbit_elements(lowered)

    def _build_env_update(self, template_id: str, text: str) -> Optional[Dict[str, Any]]:
        lowered = str(text or "").lower()
        if template_id == "data_flow" and any(word in lowered for word in ("seguro", "criptograf", "encryption", "segurança")):
            return {
                "background": {
                    "type": "linear",
                    "stops": ["#02040c", "#0f1b45"],
                }
            }
        if template_id == "cloud_rain" and any(word in lowered for word in ("tempest", "trovo", "storm")):
            return {
                "background": {
                    "type": "linear",
                    "stops": ["#07101c", "#384d6a"],
                }
            }
        if template_id == "data_flow" and any(word in lowered for word in ("distribui", "cluster", "balance", "load balancer", "escalar", "escala")):
            return {
                "camera": {"zoom": 182, "rotation": {"x": 0.22, "y": -0.44}}
            }
        return None

    @staticmethod
    def _volume_node(name: str, *, kind: str, budget: float, color: str, offset: Dict[str, float], radius: Optional[float] = None, size: Optional[Dict[str, float]] = None, material: int = 0, modifiers: Optional[List[Dict[str, Any]]] = None, animation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {"color": color, "offset": offset}
        if radius is not None:
            data["radius"] = radius
        if size is not None:
            data["size"] = size
        return {
            "name": name,
            "type": kind,
            "budget": budget,
            "material": material,
            "data": data,
            "modifiers": modifiers or [],
            "animation": animation,
        }

    def _build_data_flow_elements(self, lowered: str) -> List[Dict[str, Any]]:
        has_security = any(word in lowered for word in ("seguro", "criptograf", "encryption", "tls", "ssl", "segurança"))
        has_distribution = any(word in lowered for word in ("distribui", "cluster", "balance", "escalar", "escala", "replica"))
        has_latency = any(word in lowered for word in ("latência", "latencia", "fila", "queue", "buffer", "espera"))

        origin_offset = {"x": -72, "y": 0, "z": -8}
        hub_offset = {"x": -4, "y": 8, "z": 0}
        target_offset = {"x": 72, "y": 0, "z": 8}
        if has_distribution:
            target_offset = {"x": 82, "y": 8, "z": 18}

        elements: List[Dict[str, Any]] = [
            self._volume_node(
                "server_origin",
                kind="box",
                budget=0.10,
                color="#67e8f9" if has_security else "#38bdf8",
                offset=origin_offset,
                size={"x": 28, "y": 42, "z": 20},
                material=2,
            ),
            self._volume_node(
                "gateway_hub",
                kind="sphere",
                budget=0.10 if has_distribution else 0.09,
                color="#22d3ee" if has_security else "#a855f7",
                offset=hub_offset,
                radius=24 if has_distribution else 20,
                material=5,
                modifiers=[{"type": "jitter", "amount": 3.4 if has_latency else 2.2}],
                animation={"type": "pulse", "params": {"speed": 1.9 if has_latency else 1.6, "amplitude": 0.12 if has_latency else 0.07}},
            ),
            self._volume_node(
                "server_target",
                kind="box",
                budget=0.14 if has_distribution else 0.10,
                color="#4ade80" if has_distribution else "#22c55e",
                offset=target_offset,
                size={"x": 28, "y": 42, "z": 20},
                material=2,
            ),
            {
                "name": "packet_stream_main",
                "type": "composition",
                "budget": 0.18 if has_distribution else 0.12,
                "elements": [
                    self._volume_node(
                        f"packet_main_{idx}",
                        kind="sphere",
                        budget=0.1,
                        color="#a7f3d0" if has_security and idx % 2 == 0 else ("#f8fafc" if idx % 2 == 0 else "#38bdf8"),
                        offset={
                            "x": -52 + idx * (11 if has_distribution else 16),
                            "y": 4 + ((idx % 2) * (7 if has_latency else 4)),
                            "z": -10 + (idx % 4) * (6 if has_distribution else 3),
                        },
                        radius=3.2 if has_distribution else 4.0,
                        material=4,
                    )
                    for idx in range(12 if has_distribution else 8)
                ],
                "animation": {"type": "orbit", "params": {"speed": 0.58 if has_latency else 0.35}},
            },
        ]
        if any(word in lowered for word in ("database", "banco", "storage", "armazen")):
            elements.append(
                self._volume_node(
                    "database_cluster",
                    kind="sphere",
                    budget=0.08,
                    color="#f472b6",
                    offset={"x": 96, "y": -30, "z": 18},
                    radius=16,
                    material=3,
                )
            )
        if has_latency:
            elements.append(
                self._volume_node(
                    "buffer_queue",
                    kind="ring",
                    budget=0.09,
                    color="#f59e0b",
                    offset={"x": 24, "y": 24, "z": 0},
                    radius=22,
                    material=4,
                    animation={"type": "orbit", "params": {"speed": 0.85}},
                )
            )
        if has_distribution:
            elements.append(
                self._volume_node(
                    "distribution_fan",
                    kind="spiral",
                    budget=0.10,
                    color="#60a5fa",
                    offset={"x": 46, "y": 18, "z": 4},
                    radius=26,
                    material=4,
                )
            )
        if any(word in lowered for word in ("monitor", "telemet", "log", "observ")):
            elements.append(
                self._volume_node(
                    "telemetry_field",
                    kind="spiral",
                    budget=0.09,
                    color="#60a5fa",
                    offset={"x": 0, "y": 42, "z": -18},
                    radius=34,
                    material=4,
                )
            )
        return elements

    def _build_cloud_rain_elements(self, lowered: str) -> List[Dict[str, Any]]:
        has_storm = any(word in lowered for word in ("tempest", "trovo", "storm"))
        has_sun = any(word in lowered for word in ("sol", "sun", "luz"))
        elements: List[Dict[str, Any]] = [
            self._volume_node(
                "cloud_core",
                kind="sphere",
                budget=0.22 if has_storm else 0.18,
                color="#cbd5e1" if has_storm else "#e2e8f0",
                offset={"x": 0, "y": 34 if has_storm else 30, "z": 0},
                radius=40 if has_storm else 34,
                material=1,
                modifiers=[{"type": "jitter", "amount": 9.0 if has_storm else 6.0}, {"type": "noise", "amount": 3.8 if has_storm else 2.5, "scale": 0.8}],
            ),
            self._volume_node(
                "vapor_bloom",
                kind="sphere",
                budget=0.12,
                color="#93c5fd" if has_storm else "#7dd3fc",
                offset={"x": -18, "y": 12, "z": -10},
                radius=24,
                material=4,
                modifiers=[{"type": "jitter", "amount": 9.0}],
            ),
            {
                "name": "rain_column",
                "type": "composition",
                "budget": 0.22 if has_storm else 0.16,
                "elements": [
                    self._volume_node(
                        f"rain_drop_{idx}",
                        kind="sphere",
                        budget=0.08,
                        color="#38bdf8",
                        offset={"x": -24 + (idx % 6) * 10, "y": 8 - idx * (10 if has_storm else 8), "z": -8 + (idx % 4) * 5},
                        radius=2.2 if has_storm else 2.6,
                        material=4,
                    )
                    for idx in range(26 if has_storm else 18)
                ],
                "animation": {"type": "orbit", "params": {"speed": 0.30 if has_storm else 0.18}},
            },
        ]
        if has_sun:
            elements.append(
                self._volume_node(
                    "sunlight_arc",
                    kind="ring",
                    budget=0.08,
                    color="#fde68a",
                    offset={"x": 46, "y": 54, "z": -14},
                    radius=24,
                    material=4,
                )
            )
        if has_storm:
            elements.append(
                self._volume_node(
                    "storm_front",
                    kind="spiral",
                    budget=0.12,
                    color="#93c5fd",
                    offset={"x": 8, "y": 38, "z": -18},
                    radius=28,
                    material=4,
                )
            )
        return elements

    def _build_neural_mesh_elements(self, lowered: str) -> List[Dict[str, Any]]:
        elements = [
            self._volume_node(
                "neural_core",
                kind="sphere",
                budget=0.16,
                color="#22d3ee",
                offset={"x": 0, "y": 8, "z": 0},
                radius=22,
                material=4,
                animation={"type": "pulse", "params": {"speed": 1.8, "amplitude": 0.09}},
            ),
            self._volume_node(
                "neural_shell",
                kind="ring",
                budget=0.12,
                color="#a78bfa",
                offset={"x": 0, "y": 8, "z": 0},
                radius=38,
                material=5,
                animation={"type": "orbit", "params": {"speed": 0.42}},
            ),
            self._volume_node(
                "signal_field",
                kind="spiral",
                budget=0.14,
                color="#67e8f9",
                offset={"x": 0, "y": 10, "z": 0},
                radius=46,
                material=4,
            ),
        ]
        if any(word in lowered for word in ("fala", "voz", "voice", "speech")):
            elements.append(
                self._volume_node(
                    "voice_lattice",
                    kind="ring",
                    budget=0.09,
                    color="#f472b6",
                    offset={"x": 0, "y": -18, "z": 0},
                    radius=26,
                    material=4,
                )
            )
        return elements

    def _build_concept_orbit_elements(self, lowered: str) -> List[Dict[str, Any]]:
        return [
            self._volume_node(
                "concept_core",
                kind="sphere",
                budget=0.16,
                color="#60a5fa",
                offset={"x": 0, "y": 8, "z": 0},
                radius=24,
                material=4,
            ),
            self._volume_node(
                "concept_orbit_ring",
                kind="ring",
                budget=0.10,
                color="#c084fc",
                offset={"x": 0, "y": 8, "z": 0},
                radius=42,
                material=5,
                animation={"type": "orbit", "params": {"speed": 0.32}},
            ),
            self._volume_node(
                "concept_satellite",
                kind="sphere",
                budget=0.06,
                color="#f8fafc",
                offset={"x": 38, "y": 18, "z": 8},
                radius=8,
                material=4,
            ),
        ]

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
