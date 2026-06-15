# Browser Control Playbook

## Objetivo
Guia rapido de operacao e troubleshooting da skill `browser.control.*` em execucao real.

## Regra de Roteamento
- Use `browser.control.run` quando o usuário pedir explicitamente interação com navegador, página ou UI visual.
- Para obter informação já disponível em capabilities especializadas, prefira a capability mais precisa antes do browser.
- O browser segue como fallback legítimo para navegação, automação e validação visual quando isso for realmente necessário.

## Acoes de Diagnostico
- `browser.control.health`
- `browser.control.inspect`
- `browser.control.sync_registry`
- `browser.control.gc`

Exemplo rapido de sync:
```json
{
  "action": "browser.control.sync_registry",
  "params": {}
}
```

Resposta esperada (resumo):
```json
{
  "ok": true,
  "browser_instance_id": "chrome_ab12cd34",
  "tab_id": "tab_ef56gh78",
  "debug_port": 49231,
  "cdp_target_id": "F8B9...",
  "last_vision_observation": {},
  "registry_snapshot": {"count_instances": 1, "count_tabs": 1}
}
```

Exemplo rapido de GC sob demanda:
```json
{
  "action": "browser.control.gc",
  "params": {
    "idle_seconds": 120,
    "keep_current_instance": true
  }
}
```

Resposta esperada (resumo):
```json
{
  "ok": true,
  "gc": {
    "enabled": true,
    "ok": true,
    "expired_locks": {"expired_instance_locks": 0, "expired_tab_locks": 0},
    "closed_idle": {"closed_instances": 0, "closed_tabs": 0}
  }
}
```

## Fluxo Padrao (Health First)
1. Executar `browser.control.health` com:
   - `only_current_session=true`
   - `run_gc=false` (primeiro diagnostico sem mutacao)
2. Se `health.status=degraded`, seguir para o sintoma especifico abaixo.
3. Se necessário cleanup, repetir `browser.control.health` com `run_gc=true`.
4. Confirmar reducao de issues em `health.issues`.

Exemplo (diagnostico sem mutacao):
```json
{
  "action": "browser.control.health",
  "params": {
    "only_current_session": true,
    "include_tabs": true,
    "include_last_vision": true,
    "run_gc": false
  }
}
```

Resposta esperada (resumo):
```json
{
  "ok": true,
  "health": {
    "status": "ok",
    "issues": []
  },
  "inspect": {"ok": true},
  "sync": {"ok": true},
  "gc": {"enabled": false}
}
```

Exemplo (diagnostico + cleanup):
```json
{
  "action": "browser.control.health",
  "params": {
    "only_current_session": true,
    "run_gc": true,
    "gc_params": {
      "idle_seconds": 120,
      "keep_current_instance": true
    }
  }
}
```

Exemplo de resposta `degraded` (com leitura de issues):
```json
{
  "ok": true,
  "health": {
    "status": "degraded",
    "issues": [
      "no_active_browser_instance_bound",
      "no_active_cdp_target"
    ]
  },
  "inspect": {
    "ok": true,
    "count": 0
  },
  "sync": {
    "ok": true,
    "cdp_target_id": ""
  }
}
```

Interpretacao rapida:
- `no_active_browser_instance_bound`: nao ha instancia vinculada para a sessao atual.
- `no_active_cdp_target`: runtime sem target ativo para comando.
- Acao recomendada: iniciar `browser.control.run` (ou `step` apos `run`) e repetir `browser.control.health`.

## Tabela de Issues
| Issue | Significado | Acao imediata |
|---|---|---|
| `no_active_browser_instance_bound` | Nao existe instancia atual vinculada | Executar `browser.control.run` com objetivo simples de bootstrap |
| `no_active_cdp_target` | Runtime sem target CDP ativo | Executar `browser.control.sync_registry` e em seguida `browser.control.step` para forcar continuidade |
| `gc_execution_failed` | GC falhou na execucao | Repetir `browser.control.gc`; se persistir, revisar permissao/estado do registry |
| `no_registry_instances_for_scope` | Sem instancias no escopo filtrado | Validar `only_current_session`; se correto, iniciar novo `browser.control.run` |
| `locked_by_other_work` | Instancia ocupada por outro work | Aguardar worker ativo ou encerrar com `close_instance force=true` (se autorizado) |
| `tab_locked_by_other_work` | Aba ocupada por outro work | Aguardar worker ativo ou encerrar com `close_tab force=true` (se autorizado) |

## Runbook 60s (Recuperacao Rapida)
1. Diagnosticar sem mutacao:
```json
{"action":"browser.control.health","params":{"only_current_session":true,"run_gc":false}}
```
2. Se `degraded`, sincronizar estado:
```json
{"action":"browser.control.sync_registry","params":{}}
```
3. Tentar continuidade leve:
```json
{"action":"browser.control.step","params":{"instruction":"descreva o estado atual da pagina"}}
```
4. Se ainda degradado, executar cleanup:
```json
{"action":"browser.control.gc","params":{"idle_seconds":120,"keep_current_instance":true}}
```
5. Revalidar:
```json
{"action":"browser.control.health","params":{"only_current_session":true,"run_gc":false}}
```

Resultado esperado:
- `health.status = ok`
- `health.issues = []`
- `sync.cdp_target_id` preenchido

## Sintoma: perdeu alvo/aba (ex.: "sessao ativa perdida")
1. Executar `browser.control.sync_registry`.
2. Verificar `execution_context.cdp_target_id` e `execution_context.tab_id`.
3. Se continuar falhando, executar `browser.control.step` com instrucao simples de validacao (ex.: "descreva a pagina").
4. Confirmar em `metadata.continuation`:
   - `reattach_to_tab`
   - `target_recovery`

Sinal de recuperacao:
- `metadata.continuation.reattach_to_tab=true` ou `target_recovery.ok=true`.

## Sintoma: conflito de lock entre workers
1. Executar `browser.control.inspect` com `only_current_session=true`.
2. Checar instancia/aba com lock ativo em `instances[].lock`.
3. Se recurso estiver preso por trabalho antigo, rodar `browser.control.gc` (sob demanda).
4. Se necessário e autorizado, encerrar manualmente:
   - `browser.control.close_tab` com `force=true`
   - `browser.control.close_instance` com `force=true`

Sinal de conflito:
- erro `locked_by_other_work` ou `tab_locked_by_other_work`.

## Sintoma: mídia anterior continua tocando após troca
1. Rodar novo `browser.control.run` com `intent_class=controlar_midia`.
2. Verificar no retorno:
   - `metadata.media_singleton_cleanup`
   - `execution_context.policy_decision.media_singleton_remote_close`
3. Confirmar evento de status:
   - `code=media_singleton_cleanup`

Se ainda tocar mídia órfã:
1. `browser.control.inspect` para listar instâncias de mídia.
2. Encerrar instância órfã com `browser.control.close_instance`.

## Sintoma: registry inflado/obsoleto
1. Rodar `browser.control.gc` com `idle_seconds` curto em manutenção.
2. Repetir `browser.control.inspect` para confirmar redução de instâncias/tabs ativas.
3. Opcional: usar `browser.control.health` após GC para confirmar estado consolidado.

Sinais esperados no retorno de GC:
- `gc.expired_locks`
- `gc.closed_idle.closed_instances`

## Checklist de Validacao Rapida
1. `execution_context` possui:

## Relacionados

- [../overview.md](../overview.md): indice geral da documentacao humana.
- [../architecture/README.md](../architecture/README.md): contexto tecnico do runtime e do browser.
- [../policies/README.md](../policies/README.md): regras estaveis que cercam a operacao.
- [../reports/README.md](../reports/README.md): evidencias e auditorias de operacao.
- [../../agent/policy/README.md](../../agent/policy/README.md): politicas canônicas do agente.
- [../../agent/specs/mcp_service_and_playwright_architecture.spec.md](../../agent/specs/mcp_service_and_playwright_architecture.spec.md): contrato tecnico mais proximo do playbook.
   - `browser_instance_id`
   - `tab_id`
   - `debug_port`
   - `cdp_target_id`
2. `registry_snapshot` com contagens coerentes.
3. `metadata` presente:
   - `registry_gc`
   - em `step`, `continuation`
   - em mídia, `media_singleton_cleanup` quando aplicável.
