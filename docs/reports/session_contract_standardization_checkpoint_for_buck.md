# Session Contract Standardization Checkpoint for Buck

## 1. Objetivo da fase

Esta fase consolidou a camada de sessões e eventos como contrato canônico para o Atlas. O foco foi preparar a infraestrutura para a próxima etapa cognitiva, não reescrever a cognição em si.

O que foi padronizado:

- contrato de sessão;
- eventos canônicos;
- snapshot HTTP;
- WebSocket live;
- índices persistentes;
- thought/reasoning fora de chat;
- feedback;
- Nexus text;
- Nexus voice;
- transcript/playback;
- reconciliação de stream/mensagem.

Resultado prático:

- o backend/session contract ficou mais confiável;
- o frontend passou a consumir snapshot + WebSocket com reconciliação;
- o Buck pode focar em cognição sem tratar chat, voz e histórico como fontes caóticas.

**Fora de escopo desta fase:** cognição, prompt, `LLMResolver`, tool choice e policies agenticas não foram alterados como objetivo principal.

## 2. O que Buck pode assumir como contrato base

### Session event pipeline

- `events.jsonl` é o log canônico por sessão.
- Eventos normalizados carregam:
  - `event_id`
  - `event_type`
  - `type`
  - `session_id`
  - `turn_id`
  - `message_id`
  - `reply_to_message_id`
  - `stream_id`
  - `work_id`
  - `timestamp`
  - `source`
  - `channel`
  - `interface`
  - `target`, quando aplicável.

### Turnos

- `turn_id` canônico agrupa:
  - user message;
  - thoughts/reasoning;
  - assistant stream;
  - assistant final;
  - transcript;
  - playback;
  - complete.
- respostas curtas também geram thought no mesmo turno;
- mensagens espontâneas podem ter turno próprio;
- eventos técnicos não inventam turno conversacional.

### Mensagens

- `chat.json` contém apenas mensagens conversacionais canônicas:
  - user;
  - assistant final.
- `messages.index.json` indexa mensagens canônicas.
- reasoning/thought não entra como mensagem normal.

### Streams

- `assistant_chunk` / `final_message_chunk` usam `stream_id`.
- `complete target="stream"` fecha stream/turn.
- `message_added` reconcilia com stream existente, sem duplicar.

### Thoughts

- reasoning vai para `thoughts.index.json`.
- thoughts possuem `turn_id`.
- duration derivada:
  - `thinking_started_at`
  - `thinking_updated_at`
  - `thinking_completed_at`
  - `thinking_duration_ms`
  - `is_active`
- a UI pode renderizar thoughts como timeline, não como chat.
- a sanitização visual ainda está parcialmente no frontend; a pendência arquitetural é mover `display_title` / `display_summary` para o backend.

### Snapshot

- `GET /api/sessions/{session_id}/snapshot` é a fonte canônica para load/reload.
- Snapshot inclui:
  - `session`
  - `chat`
  - `events`
  - `indices`
  - `paths`
  - `current`
  - `runtime_metrics`
- HTTP snapshot é load/reload/reconcile.
- WebSocket é live principal.
- Polling HTTP deve ser fallback/reconciliação, não canal concorrente normal.

### Voice/Nexus

- áudio bruto continua com protocolo próprio:
  - `input.audio.start`
  - `input.audio.chunk`
  - `input.audio.end`
- a semântica derivada entra no contrato:
  - `asr.final` → `transcript.final`
  - `transcripts.index.json`
  - `tts.start/chunk/end` → `playback.started/chunk/completed`
  - `playback.index.json`
  - `voice.state` → status
  - `orb.intensity` → visual
- transcript/user/assistant/playback compartilham o mesmo `turn_id`.
- `complete target="stream"` fecha o turno de voz.

### Feedback

- feedback like/unlike é persistido em `feedback.index.json`.
- endpoint:
  - `POST /api/sessions/{session_id}/messages/{message_id}/feedback`
- feedback vincula:
  - `session_id`
  - `turn_id`
  - `message_id`
- feedback não altera cognição automaticamente ainda.
- Buck pode usar isso futuramente como sinal de aprendizado, preferência e avaliação.

## 3. Commits principais

Com base no `git log -n 20 --oneline` desta workspace, os commits mais relevantes desta fase foram:

- `dc097ca1` `fix(frontend): stabilize nexus text and voice runtime`
- `d0132f7b` `fix(sessions): close voice turns after playback`
- `ee6f6065` `feat(sessions): bridge voice events into canonical session contract`
- `38698eaa` `feat(frontend): align nexus with canonical session contract`
- `ccbd10ba` `fix(frontend): render sanitized thought summaries`
- `43af6fd1` `fix(sessions): emit reply reasoning for quick responses`
- `a9fd2901` `feat(sessions): persist assistant feedback feedback index`
- `645e89ef` `feat(sessions): expose thought duration in timeline`
- `975df5b1` `feat(frontend): render chat thoughts as timeline`
- `90f61e88` `fix(frontend): consume normalized live events in chat`
- `6167e4eb` `fix(sessions): route reasoning to thoughts index`
- `04c431e3` `feat(frontend): load chat sessions from canonical snapshot`
- `8a4f7795` `feat(events): bridge bus producers into session pipeline`
- `3fa0c22a` `test(sessions): validate snapshot reload contract`
- `09dc5084` `test(sessions): validate canonical turn snapshot grouping`
- `beb92090` `feat(sessions): use canonical turn ids across request response flow`
- `2c609b46` `test(sessions): validate canonical session snapshot contract`
- `a75ff590` `feat(sessions): add canonical session snapshot and rich indexes`
- `62e7ced3` `feat(events): route live response events through session pipeline`
- `2ea78334` `feat(sessions): add canonical session event pipeline`

## 4. Arquivos principais alterados

### Backend/session

- `src/core/session_event_pipeline.py`
- `src/core/session.py`
- `src/main.py`
- `src/core/orchestrator.py`
- `src/drivers/interfaces/server_driver.py`
- `src/server/routes/sessions.py`

### Voice

- `src/server/voice_manager.py`
- `frontend/src/hooks/useVoice.js`

### Frontend contract

- `frontend/src/pages/Chat.jsx`
- `frontend/src/pages/Nexus.jsx`
- `frontend/src/components/chat/ThoughtTimeline.jsx`
- `frontend/src/components/chat/ThoughtTimeline.utils.js`
- `frontend/src/components/chat/MessageFeedback.jsx`
- `frontend/src/components/chat/MessageItem.jsx`
- `frontend/src/components/RightIntelPanel.jsx`

### Tests

- `tests/minimal/test_session_event_pipeline.py`
- `tests/minimal/test_session_snapshot_contract.py`
- `tests/minimal/test_session_turn_snapshot_contract.py`
- `tests/minimal/test_session_snapshot_reload_contract.py`
- `tests/minimal/test_voice_session_bridge.py`
- `frontend/tests/thoughtTimeline.test.js`

## 5. Pontos que Buck NÃO deve quebrar

Buck, ao trabalhar em cognição, não deve:

- voltar a salvar reasoning em `chat.json`;
- criar mensagens assistant/user fora de `Session.add_message` / pipeline canônico;
- emitir resposta final sem `turn_id`;
- emitir thought sem `turn_id`;
- criar stream sem `stream_id`;
- finalizar resposta sem `complete target="stream"`;
- usar feedback como prompt hack imediato;
- criar evento técnico como mensagem normal;
- criar canal paralelo de voz fora de session contract;
- fazer frontend inferir correlação que o backend deveria emitir.

## 6. Pontos que Buck pode aproveitar

Buck pode usar os novos índices e eventos para:

- `feedback.index.json` para avaliação e preferência futura;
- `thoughts.index.json` para pós-mortem cognitivo;
- `events.jsonl` para auditoria de raciocínio e execução;
- `turns.index.json` para medir duração e qualidade por turno;
- `workers.index.json` para entender execução de capacidades;
- `transcripts.index.json` para voz;
- `playback.index.json` para respostas faladas;
- `snapshot` para reconstrução confiável de contexto.

## 7. Pendências reais

Esta é uma base sólida, mas ainda existem pendências não bloqueadoras:

- estabilizar typewriter/transcript live do Nexus;
- mover `display_title` / `display_summary` de thought para o backend;
- usar feedback para aprendizado real;
- Telegram media/attachments no contrato canônico;
- limpar worktree sujo de outras frentes/agentes;
- UI opcional de transcript/playback;
- analytics de qualidade por turno;
- revisar o live close do Nexus para depender menos do snapshot reconcile.

## 8. Estado do worktree

O worktree atual está sujo por mudanças desta fase e por ruído paralelo de outras frentes/agentes. O estado capturado no momento deste checkpoint foi:

**Nota:** este status foi capturado em workspace sujo e mistura mudanças commitadas, mudanças paralelas de outros agentes e pendências reais. Não usar esta lista como backlog direto sem nova triagem.

```text
M .gitignore
M agent/.gitignore
D agent/README.md
M agent/policy/adequation.policy.md
M agent/policy/overview.md
M agent/policy/session-event-contract.policy.md
M agent/specs/project.spec.md
M agent/specs/project.stat.md
M agent/specs/session-event-contract.spec.md
M agent/specs/session-event-contract.stat.md
M agent/test/test_attachment_delivery_contract.py
M docs/architecture/overview.md
D docs/concepts/market-learning-engine.concept.md
M docs/contracts/overview.md
M docs/guides/agent_runtime_v2_smoke_rollback_checklist.md
M docs/guides/browser_control_playbook.md
M docs/guides/testing_guide.md
M docs/legacy/ALL_IN_ONE_AGENT_SPEC.md
M docs/plans/overview.md
M docs/policies/commit-safety.policy.md
M docs/policies/recovery-grounding.policy.md
M docs/policies/spec-documentation.policy.md
M docs/reports/overview.md
M frontend/src/components/AssistCards.jsx
M frontend/src/components/AtlasOrbCanvas.jsx
M frontend/src/components/CapabilityIcon.jsx
M frontend/src/components/ModelPoolManager.jsx
M frontend/src/components/PageHeader.jsx
M frontend/src/components/RemoteAccessIndicator.jsx
M frontend/src/components/ThemeToggle.jsx
M frontend/src/components/WegenaParticleCanvas.jsx
M frontend/src/components/chat/ChatInputArea.jsx
M frontend/src/components/chat/MessageAttachments.jsx
M frontend/src/components/chat/MessageItem.jsx
M frontend/src/components/chat/ThoughtTimeline.utils.js
M frontend/src/components/chat/TypewriterMarkdown.jsx
M frontend/src/components/chat/WorkUnitInspector.jsx
M frontend/src/hooks/useVoice.js
M frontend/src/index.css
M frontend/src/layouts/DashboardLayout.jsx
M frontend/src/pages/Capabilities.jsx
M frontend/src/pages/Chat.jsx
M frontend/src/pages/CognitionDiagnostics.jsx
M frontend/src/pages/Memory.jsx
M frontend/src/pages/MessagingAccess.jsx
M frontend/src/pages/Nexus.jsx
M frontend/src/pages/Security.jsx
M frontend/src/pages/Settings.jsx
M frontend/src/pages/Setup.jsx
M frontend/src/pages/Tasks.jsx
M frontend/tests/thoughtTimeline.test.js
D src/capabilities/browser_control/IMPLEMENTATION_PLAN.md
M src/capabilities/browser_control/contract.json
M src/capabilities/notifications/contract.json
M src/capabilities/registry.py
M src/capabilities/system_control/capability.py
M src/capabilities/system_control/contract.json
M src/core/observation.py
M src/core/orchestrator.py
M src/core/resolution/llm_resolver.py
M src/drivers/interfaces/server_driver.py
M src/drivers/interfaces/telegram/telegram_driver.py
M src/drivers/providers/ollama/llm.py
M src/providers/llama_server/index.json
D src/providers/local_openai/index.json
D src/providers/local_qwen/index.json
M src/providers/ollama/index.json
M src/providers/openai/index.json
M src/server/routes/capabilities.py
M src/server/voice_manager.py
M src/services/llm/manager.py
M src/services/llm/prompt_composer.py
M tests/minimal/test_capability_registry_discovery_metadata.py
M tests/minimal/test_llm_resolver_failure_replan_guard.py
M tests/minimal/test_mcp_llm_alias_and_recovery.py
M tests/minimal/test_prompt_composer_assistive_mode.py
M tests/minimal/test_prompt_composer_operating_model.py
M tests/minimal/test_system_control_consult_tools.py
?? agent/policy/observability.policy.md
?? agent/scripts/check_braces_cap.py
?? docs/contracts/nexus_live_transcript_contract.md
?? docs/plans/browser_control_implementation.md
?? docs/reports/atlas_ui_ux_audit_report.md
?? frontend/src/components/ErrorBoundary.jsx
?? frontend/src/components/chat/MessageFeedback.jsx
?? tests/minimal/test_confidence_diagnostics_persistence.py
?? tests/minimal/test_llm_manager_provider_fallback.py
?? tests/minimal/test_llm_resolver_confidence_diagnostics.py
```

Separação útil para o Buck:

- **mudanças desta fase já consolidadas em commit:** sessão, snapshot, thoughts, feedback, voice bridge, Nexus text/voice runtime;
- **sujeira paralela:** há muitos arquivos de docs, capabilities, providers e frontend que não fazem parte do checkpoint;
- **temporários/untracked:** `docs/contracts/nexus_live_transcript_contract.md`, `frontend/src/components/ErrorBoundary.jsx`, `frontend/src/components/chat/MessageFeedback.jsx` e outros artefatos auxiliares devem ser tratados como ruído até confirmação explícita.

## 9. Validações executadas

Durante esta fase, as validações principais usadas foram:

- `python3 -m py_compile` nos módulos de session, voice e bridge;
- `PYTHONPATH=src ./env/bin/python -m pytest -q` nos testes mínimos de session pipeline/snapshot/voice bridge;
- `cd frontend && npm run build`;
- smokes manuais do Chat texto;
- smokes manuais do Nexus texto;
- smokes manuais do Nexus voice;
- reload/snapshot;
- transcript/playback no fluxo de voz.

## 10. Resumo executivo para Buck

O contrato de sessão agora fornece uma base canônica para que a cognição trabalhe sem depender de inferência frágil no frontend. Thoughts, mensagens, streams, voz, playback e feedback estão indexados por sessão/turno. Buck deve consumir o contrato canônico existente. Não deve criar caminhos paralelos para thoughts, messages, voice, playback ou feedback.
