# Diagnostico Kernel/Orquestrador/Planner (Sem Patch de Kernel)

Data da analise: 2026-03-08  
Escopo: identificar causas de respostas otimistas indevidas, loops e problemas de parser/saida invalida observados no fluxo `browser.control.run`.

## 1) Problemas confirmados no Kernel/Orquestrador

1. Log de execucao "successful" antes da classificacao semantica real do resultado
- Evidencia:
  - `src/core/orchestrator.py:2721` loga `Tool execution successful`.
  - A avaliacao real de sucesso/falha so ocorre depois em `src/core/orchestrator.py:2814` (`_assess_action_result`).
- Impacto:
  - Telemetria/confusao operacional: parece sucesso mesmo quando o payload final e falha semantica.
  - Dificulta depuracao e cria leitura enganosa em producao.
- Recomendacao:
  - Renomear esse log para "dispatch completed".
  - Registrar "execution_success/execution_failure" somente apos `_assess_action_result`.

2. Re-entrada agressiva de policy override para media sem cooldown de erro estrutural
- Evidencia:
  - Override hard para YouTube playback em `src/core/orchestrator.py` (`_apply_media_decision_policy`), com conversao recorrente para `browser.control.run`.
- Impacto:
  - Em falha estrutural (ex.: parser/planner abort), o loop volta para `youtube.search.find -> browser.control.run` repetidamente.
- Recomendacao:
  - Introduzir cooldown por sessao/objetivo para `browser.control.run` apos erros estruturais (`PLANNER_OUTPUT_INVALID`, `SKILL_EXECUTION_ERROR`, loop mismatch).
  - Exigir estrategia alternativa antes de novo override.

3. Recovery conversational pode afirmar sucesso por "sucesso tecnico" e nao "objetivo confirmado"
- Evidencia:
  - Prompt da recuperacao em `src/core/orchestrator.py:4158+` contem regra: "If the last tool succeeded, summarize the result conversationally."
- Impacto:
  - Mensagens como "deu certo" podem surgir sem confirmacao de efeito real do objetivo do usuario.
- Recomendacao:
  - No recovery, para `browser.control.run`, exigir evidencia de objetivo (estado/marker/url/resultado final) antes de linguagem de conclusao.
  - Caso sem evidencia, responder neutro de progresso.

4. Semantica de success/failure depende fortemente do contrato de skill (friccao de fronteira)
- Evidencia:
  - `_assess_action_result` em `src/core/orchestrator.py:4040+` confia em `ok/status` do payload da skill.
- Impacto:
  - Se skill retornar `ok:true` com `result.status:error`, o kernel tende a classificar sucesso.
- Recomendacao:
  - Harden no kernel: para respostas estruturadas com `result.status in {error,failed,failure}`, tratar como falha mesmo com `ok:true`.

## 2) Problemas de "thought/planner/output parser" observados

1. Saida invalida do planner (JSON malformado) causa abort por parse consecutivo
- Evidencia de log:
  - Parse failures consecutivas com payload tipo `"thought: ..."` sem chave JSON valida.
- Impacto:
  - Abort precoce do planner (`PLANNER_OUTPUT_INVALID`), com degradacao do fluxo.
- Causa:
  - Modelo retornando JSON quebrado sob carga/complexidade de contexto.
- Recomendacao no kernel (sem patch aplicado aqui):
  - Instrumentar metrica de parse invalid por modelo/turno.
  - Fallback deterministico apos primeira falha (nao esperar 2 falhas para todo caso).
  - Opcional: reduzir prompt payload quando detectar parser instability.

2. Mistura de "sucesso tecnico da tool" vs "sucesso de objetivo do usuario"
- Evidencia:
  - Mesmo com `command_id="err"` no resultado interno do planner, o fluxo externo pode seguir como "acao executada".
- Impacto:
  - Mensagens de conclusao desalinhadas com o estado real do objetivo.
- Recomendacao:
  - No kernel, criar estado distinto:
    - `dispatch_ok` (chamada executada)
    - `goal_progress_ok` (efeito observado)
    - `goal_done` (criterio de encerramento atingido)

## 3) Correcao aplicada apenas na Skill (neste ciclo)

1. Cross-loop teardown da runtime
- Adicionado `force_close()` sincrono em `src/skills/browser_control/runtime.py` para evitar erro `Future attached to a different loop` ao trocar loop.
- `BrowserControlSkill._ensure_runtime` agora usa `force_close()` quando detecta loop diferente.

2. `browser.control.run` nao reporta mais sucesso falso
- `src/skills/browser_control/browser_control_skill.py` agora verifica `response.status`.
- Se `response.status in {error,failed,failure}`:
  - `ok = false`
  - `status = "error"`
  - `run_status = "failed"` (playback encerra como failed)
  - `error` propagado no payload final.

3. Parser sanitization da skill planner corrigido
- `src/skills/browser_control/planner.py::_clean_json` removido regex defeituoso que introduzia JSON invalido.
- Adicionadas correcoes heuristicas seguras para chaves comuns malformadas (`thought`, `step_status`, `action`, `args`, `response_text`).

## 4) Conclusao

- Causa raiz primaria do incidente foi combinacao de:
  1) bug de contrato/estado na skill (ok=true com erro interno), e
  2) politicas do kernel que tratam "sucesso tecnico" como "conclusao conversacional".
- Com os patches da skill aplicados, a classificacao tende a ficar mais fiel.
- Ainda ha ganhos importantes a fazer no kernel para evitar loops, logs enganosos e respostas otimistas sem evidencia.
