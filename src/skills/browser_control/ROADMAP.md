# Browser Control Roadmap

## Objetivo
Evoluir a skill `browser_control` para operar com controle robusto de instancias/abas, politica automatica de roteamento e telemetria auditavel, sem exigir que o LLM gerencie detalhes de CDP (porta, target, instancia).

## Principios
- Compatibilidade retroativa: chamadas antigas continuam funcionando.
- Decisao de sessao/aba no backend: LLM nao escolhe porta nem target.
- Estado global observavel: supervisor pode consultar inventario e saude.
- Seguranca operacional: cleanup de recursos ociosos e reset no boot.

## Escopo Funcional (Target)
- Registro global de instancias e abas (registry/index).
- IDs estaveis para rastreio:
  - `browser_instance_id`
  - `tab_id`
  - `debug_port`
  - `cdp_target_id`
- Politica automatica de roteamento:
  - `reuse_tab`
  - `new_tab`
  - `new_app_window`
  - `new_instance`
- Classificacao de intencao de navegador via contrato:
  - `controlar_midia`
  - `realizar_pesquisa`
  - `automacao_ui`
  - `validacao_visual`
  - `manutencao`
- Regra de midia:
  - Apenas 1 aba de midia ativa por usuario/sessao logica.
  - Ao abrir nova midia, fechar a anterior e atualizar registry.
- Telemetria e auditoria com metadados de navegador/tab em eventos e chat.

## Nao Escopo (Inicial)
- Multi-browser (Firefox/Edge/Safari).
- Sincronizacao distribuidade em multiplos processos/hosts.
- Reproducao de sessoes CDP apos restart (apenas reset e reconciliacao).

## Arquitetura Proposta
1. BrowserSessionRegistry (global)
- Persistencia em `data/browser_registry.json` (ou equivalente).
- Estruturas:
  - Instancia: id, porta, ws, modo, owner, worker/task, status, last_used_at.
  - Aba: id, target_id, url, titulo, role, in_use, last_used_at.
- APIs:
  - create/update/get/list
  - mark_in_use/release
  - close_if_idle
  - reset_active_indexes_on_boot

2. BrowserSessionPolicy
- Entrada: `goal`, `url`, `intent_class`, contexto de worker/task.
- Saida: decisao de roteamento + justificativa curta.
- Regras:
  - Midia favorece app mode e singleton de aba de midia.
  - Pesquisa/confirmacao favorece tab normal reutilizavel.
  - Se target invalido/stale: reattach ou nova instancia.

3. BrowserRuntime Adapter
- Runtime passa a receber `instance_id` e `tab_id` resolvidos.
- Antes de cada acao: validar/reattach no `cdp_target_id`.
- Porta CDP automatica (sem valor fixo hardcoded).

4. Supervisor/Audit Integration
- Incluir em status/eventos:
  - `browser_instance_id`, `tab_id`, `debug_port`, `intent_class`, `policy_decision`, `reused`.
- Permitir consulta global (somente leitura) para supervisao cross-session.

## Roadmap por Fase

### Fase 0 - Correcoes de Base (bloqueadores atuais)
- Corrigir incompatibilidade de schema para acao `vision`.
- Ajustar status final de playback (nao marcar `completed` em erro).
- Eliminar duplicidades/erros obvios de contrato (ex.: tipo de `result`).
- Adicionar ignore de artefatos de profile/sessoes.

### Fase 1 - Registry Global + Reset no Boot
- Implementar `BrowserSessionRegistry`.
- Resetar indices ativos ao subir servico:
  - marcar sessoes anteriores como stale/invalid.
- Injetar metadata basica no retorno da skill.

### Fase 2 - Policy de Roteamento Automatizada
- Implementar `BrowserSessionPolicy`.
- Selecao automatica: reusar aba, nova aba, app, nova instancia.
- Alocacao de porta CDP dinamica por instancia.

### Fase 3 - Midia Singleton + Lifecycle
- Enforce de 1 aba de midia por escopo definido.
- Fechamento automatico da midia anterior ao trocar URL de midia.
- Garbage collection de instancias/abas idle sem worker ativo.
- Fechamento remoto best-effort das instancias de midia substituidas usando `debug_port`.

### Fase 4 - Observabilidade e Supervisao
- APIs/acoes de manutencao:
  - listar instancias/abas abertas
  - fechar aba
  - fechar instancia ociosa
  - sincronizar registry
  - acionar GC sob demanda (`browser.control.gc`)
- Exibir IDs no chat/status quando relevante.

### Fase 5 - Normalizacao de Vision
- Definir contrato canonico de observacao visual.
- Adapter para browser_control consumir o contrato sem quebrar outras skills.
- Regressao completa de fluxos multimodais.

## Compatibilidade Retroativa
- `intent_class` sera opcional no inicio.
- Default de `intent_class`: `realizar_pesquisa`.
- Chamadas legadas de `browser.control.run` continuam validas.
- Novos campos de metadata entram como opcionais no output.

## Riscos e Mitigacoes
- Risco: corridas entre workers disputando mesma instancia.
  - Mitigacao: lock por `instance_id/tab_id` e flag `in_use`.
- Risco: drift entre registry e estado real do CDP.
  - Mitigacao: reconciliacao periodica e sync on-demand.
- Risco: limpeza fechar recurso em uso.
  - Mitigacao: checagem de ownership + heartbeat recente + grace period.

## Criterios de Aceite
- Nenhuma acao executa em aba errada quando IDs estiverem definidos.
- Nenhuma nova instancia usa porta CDP fixa.
- Regra de midia singleton aplicada e auditavel.
- Supervisor consegue listar estado global e identificar owner/worker.
- Reinicio do servico invalida indices ativos antigos sem corromper sessao atual.

## Entregaveis
- Documento de design tecnico (detalhando schema e APIs internas).
- Implementacao incremental por fase com feature flags.
- Suite minima de testes:
  - unitarios de policy/registry
  - integracao de roteamento/tab targeting
  - regressao de fluxo de midia e pesquisa

## Exemplos Rapidos de Auditoria
- Status de cleanup de midia (`send_status.code=media_singleton_cleanup`):
```json
{
  "code": "media_singleton_cleanup",
  "media_cleanup": {
    "closed": 1,
    "remote_close": {"attempted_instances": 1, "closed_targets": 1, "errors": 0}
  }
}
```

- Metadados de continuidade em `browser.control.step`:
```json
{
  "metadata": {
    "continuation": {
      "reattach_to_tab": true,
      "target_recovery": {"ok": false, "strategy": "skipped"}
    }
  }
}
```
