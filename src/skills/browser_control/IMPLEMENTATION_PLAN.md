# Browser Control Implementation Plan (Kernel-Aligned)

## Contexto
Este plano detalha a execucao do roadmap considerando a arquitetura atual do kernel.

## Contrato Atual do Kernel (base de integracao)
- O skill recebe `exec_context` via `SkillRegistry.dispatch`.
- Campos relevantes hoje:
  - `session`: `_SkillSessionView` (somente leitura; sem `add_message`).
  - `callbacks`: somente `send_status` (demais callbacks nao sao expostos para skill).
  - `session_id`, `work_id`, `user_input`, `allowed_actions`.
  - `touch_work_context(work_id, patch)` para persistencia incremental de estado de trabalho.
  - `playback_service` opcional.
- Implicacao: toda telemetria operacional do browser para supervisor/chat deve ir por:
  - `callbacks["send_status"](...)`
  - `touch_work_context(...)`
  - retorno estruturado da skill (quando aplicavel)

## Objetivo de Entrega
- Controle deterministico de instancia/aba sem expor complexidade ao LLM.
- Registro global observavel e resetavel no boot.
- Politica automatica de roteamento (tab/app/instancia).
- Regra de midia singleton.
- Compatibilidade com contrato atual de skill/kernel.

## Rebaseline de Status (2026-03-08)
- Entregue:
  - Registry global + reset no boot (EPIC B/C base).
  - Policy de sessao com `intent_class` e app mode para midia (EPIC D parcial/F parcial).
  - Metadados tecnicos em `execution_context` + `send_status` + `touch_work_context` (EPIC G parcial).
  - Acoes administrativas `inspect`, `close_tab`, `close_instance`, `sync_registry` (EPIC H parcial).
  - `step` da skill implementado para continuidade com runtime ativo (lacuna critica fechada).
  - Guard de fechamento administrativo (`close_tab/close_instance`) com bloqueio por ownership/in_use e override por `force=true`.
  - Lock logico por `instance_id` com lease no registry, aplicado em `run/step` (acquire/release por session/work).
  - Lock logico por `tab_id` com lease no registry, aplicado em `run/step` para reduzir colisao intra-instancia.
  - GC de registry: limpeza de locks expirados e fechamento de instancias ociosas (`close_if_idle`) via feature flag.
  - Granularidade de policy para `reuse_tab/new_tab` por dominio (com abertura automatica de nova aba no runtime).
  - EPIC I parcial: contrato canonico de vision (`vision_contract.py`) + adapter no planner para normalizar observacao visual.
  - Persistencia da ultima observacao de vision no `execution_context` e no `touch_work_context` para continuidade/auditoria.
  - `inspect` com opcao de expor `last_vision_observation` para supervisao manual.
  - `sync_registry` incluindo `last_vision_observation` para consulta rapida de estado.
  - Acao administrativa `browser.control.gc` para GC sob demanda do registry (alem do modo automatico por flag).
  - Singleton de midia com fechamento remoto best-effort por `debug_port` das instancias substituidas.
  - Telemetria de `media_singleton_cleanup` emitida via `send_status` para supervisao em tempo real.
  - Retorno estruturado da skill com `metadata` (run/step, inclusive falhas de lock; incluindo cleanup de midia e GC) para analise offline.
  - `metadata.continuation` no `step` com resumo direto de `reattach_to_tab` e `target_recovery`.
  - Playbook operacional de troubleshooting em `docs/browser_control_playbook.md`.
- Parcial:
  - Singleton de midia fecha no registry, mas ainda sem garantia de encerramento de processo externo em todos os casos.
  - Roteamento ainda pode evoluir para regras mais finas por tipo de dominio/fluxo, mas `reuse_tab/new_tab` base ja esta ativo.
  - Snapshot consolidado de abas foi adicionado ao retorno da skill, mas falta validacao E2E em ambiente real.
- Pendente:
  - EPIC I restante: mapeamento adicional com `vision.*` no orchestrator apenas se surgirem incompatibilidades.
  - Testes de integracao E2E reais (continuacao multi-turn, disputa entre workers, recovery de target stale).

## Backlog Tecnico por Epic

### EPIC A - Hardening base da skill (pre-requisito)
- BC-A1: Corrigir schema `vision` em `ToonResponse`.
  - Arquivo: `src/skills/browser_control/schemas.py`
- BC-A2: Corrigir `playback` final para nao forcar `completed` em erro.
  - Arquivo: `src/skills/browser_control/browser_control_skill.py`
- BC-A3: Ajustar `contract.json` para refletir output real (`result` objeto).
  - Arquivo: `src/skills/browser_control/contract.json`
- BC-A4: Ignorar artefatos de profile/sessoes no git.
  - Arquivo: `.gitignore`

### EPIC B - Registry global de browser
- BC-B1: Criar modulo de estado global `BrowserSessionRegistry`.
  - Arquivo novo: `src/skills/browser_control/session_registry.py`
- BC-B2: Definir schema de persistencia (`data/browser_registry.json`).
  - Arquivo novo: `src/skills/browser_control/registry_schema.py`
- BC-B3: Implementar lock/thread-safety e IO atomico.
  - Arquivo: `src/skills/browser_control/session_registry.py`
- BC-B4: API interna minima:
  - `create_instance`, `update_instance`, `close_instance`
  - `create_tab`, `update_tab`, `close_tab`
  - `list_instances`, `list_tabs`, `acquire_tab`, `release_tab`

### EPIC C - Reset e lifecycle no boot (global)
- BC-C1: Inicializar service do registry no `Kernel.__init__`.
  - Arquivo: `src/main.py`
- BC-C2: Executar `reset_active_indexes_on_boot` no startup.
  - Arquivo: `src/main.py`
- BC-C3: Expor registry para orchestrator/skills via kernel.
  - Arquivo: `src/main.py`

### EPIC D - Policy automatica de roteamento
- BC-D1: Criar `BrowserSessionPolicy`.
  - Arquivo novo: `src/skills/browser_control/session_policy.py`
- BC-D2: Adicionar `intent_class` opcional no contrato da skill.
  - Arquivo: `src/skills/browser_control/contract.json`
- BC-D3: Resolver decisao sem LLM:
  - `reuse_tab`, `new_tab`, `new_app_window`, `new_instance`.
  - Arquivo: `src/skills/browser_control/browser_control_skill.py`
- BC-D4: Porta CDP dinamica por instancia (sem hardcode 9222).
  - Arquivo: `src/skills/browser_control/runtime.py`

### EPIC E - Alinhamento runtime/planner com IDs de sessao/aba
- BC-E1: Runtime aceitar/propagar `browser_instance_id` e `tab_id`.
  - Arquivo: `src/skills/browser_control/runtime.py`
- BC-E2: Planner executar sempre no `tab_id` alvo resolvido.
  - Arquivo: `src/skills/browser_control/planner.py`
- BC-E3: Antes de acao, validar `target_id` e reattach quando necessario.
  - Arquivo: `src/skills/browser_control/runtime.py`

### EPIC F - Midia singleton e modo app
- BC-F1: Implementar deteccao de dominio elegivel para app mode.
  - Arquivo: `src/skills/browser_control/session_policy.py`
- BC-F2: Regra: apenas uma aba de midia ativa por escopo logico.
  - Arquivo: `src/skills/browser_control/session_policy.py`
- BC-F3: Ao abrir nova midia, encerrar midia anterior e atualizar registry.
  - Arquivo: `src/skills/browser_control/browser_control_skill.py`
- BC-F4: `--app=<url>` somente em `intent_class=controlar_midia`.
  - Arquivo: `src/skills/browser_control/runtime.py`

### EPIC G - Supervisor, audit e contexto de work
- BC-G1: Publicar metadados tecnicos por `send_status`.
  - Arquivo: `src/skills/browser_control/browser_control_skill.py`
- BC-G2: Persistir metadados em `touch_work_context`.
  - Arquivo: `src/skills/browser_control/browser_control_skill.py`
- BC-G3: Campos padrao:
  - `browser_instance_id`, `tab_id`, `debug_port`, `intent_class`, `policy_decision`, `reused`
- BC-G4: Garantir que payloads aparecam em auditoria de work/supervisor.
  - Arquivos: `src/core/orchestrator.py`, `src/core/scheduler.py` (ajustes minimos se necessario)

### EPIC H - Operacoes administrativas e supervisao global
- BC-H1: Acoes internas para inventario e manutencao:
  - `browser.control.inspect`
  - `browser.control.close_tab`
  - `browser.control.close_instance`
  - `browser.control.sync_registry`
  - Arquivos: `src/skills/browser_control/contract.json`, `src/skills/browser_control/browser_control_skill.py`
- BC-H2: Regras de seguranca:
  - nunca fechar recurso `in_use` por outro worker sem forca explicita.
  - validar ownership (session/work) quando aplicavel.

### EPIC I - Contrato canonico de vision (sem quebrar outras skills)
- BC-I1: Definir resposta canonica para observacao visual consumivel por browser.
  - Arquivo novo: `src/skills/browser_control/vision_contract.py`
- BC-I2: Adapter de consumo no planner/browser.
  - Arquivo: `src/skills/browser_control/planner.py`
- BC-I3: Compatibilidade com `vision.*` existente no orchestrator.
  - Arquivo: `src/core/orchestrator.py` (somente se precisar de mapeamento extra)

## Ordem de Execucao Recomendada
1. EPIC A
2. EPIC B + C
3. EPIC D + E
4. EPIC F
5. EPIC G + H
6. EPIC I

## Feature Flags (rollout seguro)
- `skills.browser_control.registry_enabled` (default: true)
- `skills.browser_control.policy_enabled` (default: false na fase inicial)
- `skills.browser_control.media_singleton_enforced` (default: false)
- `skills.browser_control.app_mode_enabled` (default: false)
- `skills.browser_control.registry_gc_enabled` (default: false)

## Testes Minimos por Fase
- Unitarios:
  - policy decision matrix
  - registry concorrencia e persistencia
  - media singleton transitions
- Integracao:
  - selecao correta de tab/instance em sequencia de acoes
  - troca de midia fecha aba anterior
  - restart do servico invalida indices ativos antigos
- Regressao:
  - `browser.control.run` legado sem `intent_class`
  - playback/status continuam funcionando com callbacks filtrados

## Definicao de Pronto (DoD)
- Todo evento operacional relevante do browser inclui IDs de instancia/aba.
- Nenhuma nova sessao usa porta CDP fixa.
- Nao ha acao em aba errada quando contexto de tab estiver definido.
- Reinicio do kernel nao tenta reutilizar sessao CDP antiga.
- Contrato da skill e output real ficam consistentes.

## Exemplos de Payload (Referencia Operacional)
- `browser.control.run` (resumo):
```json
{
  "ok": true,
  "execution_context": {
    "browser_instance_id": "chrome_ab12cd34",
    "tab_id": "tab_ef56gh78",
    "debug_port": 49231,
    "cdp_target_id": "F8B9...",
    "intent_class": "controlar_midia",
    "reused_instance": true,
    "policy_decision": {
      "route": "reuse_tab",
      "reason": "same_session_reuse",
      "media_singleton_closed": 1,
      "media_singleton_remote_close": {
        "attempted_instances": 1,
        "closed_targets": 1,
        "errors": 0
      },
      "registry_gc": {"enabled": true, "ok": true}
    }
  },
  "metadata": {
    "media_singleton_cleanup": {
      "closed": 1,
      "remote_close": {"attempted_instances": 1, "closed_targets": 1, "errors": 0}
    },
    "registry_gc": {"enabled": true, "ok": true}
  },
  "registry_snapshot": {"count_instances": 2, "count_tabs": 2}
}
```

- `browser.control.step` (resumo):
```json
{
  "ok": true,
  "execution_context": {
    "policy_decision": {
      "route": "step_continue",
      "reattach_to_tab": true,
      "target_recovery": {"ok": false, "strategy": "skipped"}
    },
    "last_vision_observation": {
      "schema": "browser_control.vision.v1",
      "summary": "Botao pular anuncio visivel",
      "coordinates": [{"x": 812, "y": 134}]
    }
  },
  "metadata": {
    "registry_gc": {"enabled": false},
    "continuation": {
      "reattach_to_tab": true,
      "target_recovery": {"ok": false, "strategy": "skipped"}
    }
  }
}
```

- `send_status` de cleanup de midia:
```json
{
  "action": "browser.control.run",
  "code": "media_singleton_cleanup",
  "label": "Media singleton cleanup applied.",
  "media_cleanup": {
    "closed": 1,
    "remote_close": {"attempted_instances": 1, "closed_targets": 1, "errors": 0}
  }
}
```
