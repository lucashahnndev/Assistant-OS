import logging
import os
import uuid
import asyncio
from typing import Dict, Any, List
from ..base import CapabilityBase
from services.llm.manager import LLMManager

logger = logging.getLogger("WegenaCapability")

FINAL_WEG_SYSTEM_PROMPT = """Você é um Diretor de Arte e compositor de cenas para o motor de partículas Wegena.
Sua tarefa é gerar uma cena `.weg` EXTREMAMENTE RICA e COMPLEXA com base no pedido.

REGRAS:
1. MAXIMALISMO: Use múltiplos elementos, camadas e detalhes. Use de 8 a 12 `@Node`s no mínimo.
2. ORÇAMENTO (BUDGET): A soma de TODOS os `budget`s na cena DEVE ser EXATAMENTE {budget}.
3. MOVIMENTO: A cena NÃO PODE ser estática. Use `animation: { type: "orbit", params: { speed: 0.5 } }` ou `pulse`.
4. TERRENOS E FUNDO: Sempre use `@Background` e `@FX`.
5. LIMITE: Densidade sugerida {max_particles}. Nível de composição: {fidelity}.
"""

class WegenaCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self.llm = LLMManager()

    @property
    def name(self) -> str:
        return "wegena"

    @property
    def actions(self) -> List[str]:
        return ["generate_scene"]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        if action_id == "generate_scene":
            return self._generate_scene(params, context)
        return {
            "ok": False,
            "status": "error",
            "provider": self.name,
            "data": {},
            "metadata": {"error": f"Unknown action: {action_id}"}
        }

    def _generate_scene(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        description = params.get("description", "Uma cena abstrata com partículas brilhantes.")
        session_id = context.get("session_id", "default")
        
        # Obter configs (com fallback)
        fidelity = self.config.get("composition_fidelity", "high")
        budget = float(self.config.get("budget_limit", 1.0))
        max_particles = int(self.config.get("max_particles", 70000))
        
        system_prompt = FINAL_WEG_SYSTEM_PROMPT.format(
            budget=budget,
            max_particles=max_particles,
            fidelity=fidelity
        )

        try:
            # Geração usando LLM
            logger.info(f"WegenaCapability: Gerando cena para '{description}'")
            # Rodar sincronamente bloqueando a thread do capability executor (ok para actions)
            # Mas idealmente chamamos de forma assíncrona ou rodamos em event loop
            import re
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                asyncio.to_thread(
                    self.llm.generate_text,
                    prompt=f"Gere a cena: {description}",
                    system_prompt=system_prompt,
                    max_tokens=1800,
                )
            )
            loop.close()

            # Extrair script
            weg_script = result.strip()
            weg_match = re.search(r"```weg\s*([\s\S]*?)```", weg_script, re.IGNORECASE)
            if weg_match:
                weg_script = weg_match.group(1).strip()
            else:
                code_match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```", weg_script)
                if code_match and ("@Node" in code_match.group(1) or "@World" in code_match.group(1)):
                    weg_script = code_match.group(1).strip()

            if not weg_script or "@" not in weg_script:
                raise Exception("Script .weg não pôde ser gerado ou é inválido.")

            # Salvar como artefato
            os.makedirs("data/workspace/wegena", exist_ok=True)
            filename = f"scene_{uuid.uuid4().hex[:8]}.weg"
            filepath = os.path.abspath(os.path.join("data/workspace/wegena", filename))
            
            with open(filepath, "w") as f:
                f.write(weg_script)
                
            return {
                "ok": True,
                "status": "success",
                "provider": self.name,
                "data": {
                    "scene_path": filepath,
                    "media_paths": [filepath],
                    "metadata": {
                        "fidelity": fidelity,
                        "budget": budget,
                        "description": description
                    }
                },
                "metadata": {"action": "generate_scene"}
            }

        except Exception as e:
            logger.error(f"Erro em WegenaCapability: {e}")
            return {
                "ok": False,
                "status": "error",
                "provider": self.name,
                "data": {},
                "metadata": {"error": str(e)}
            }

    def get_documentation(self) -> str:
        return (
            "Gera cenas visuais 3D em linguagem procedimental (.weg) baseadas no motor de partículas Wegena. "
            "Sempre use isso quando o usuário solicitar para ver algo, visualizar um conceito ou criar uma paisagem 3D. "
            "Ao chamar a action 'generate_scene', o motor cuidará da geração do código e devolverá um arquivo de mídia."
        )
