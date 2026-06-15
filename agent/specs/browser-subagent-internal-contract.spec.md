# BrowserSubagent Internal Contract

Data: 2026-06-09
State mirror: [browser-subagent-internal-contract.stat.md](browser-subagent-internal-contract.stat.md).

## Propósito

Esta spec define o contrato interno do `BrowserSubagent`.

`BrowserSubagent` é um subagente operacional legítimo do browser.
Ele pode planejar, diagnosticar e registrar progresso interno.
Ele nao e o pensamento primário do Atlas.
Ele nao escolhe se o Atlas deve usar browser.
Ele controla apenas o fluxo interno da capability browser e retorna observação estruturada para o restante do runtime.

## 1. Papel do BrowserSubagent

- produzir planejamento operacional interno para o browser;
- manter diagnóstico e memória interna de execução;
- registrar progresso, telemetria e evidência;
- decidir passos internos da capability browser;
- devolver observação estruturada para o Atlas/capability.

## 2. Fronteira de autoridade

O subagente opera sob a seguinte fronteira:

`source=browser_control`
`agent_role=subagent`
`semantic_authority=internal_browser_only`
`not_user_facing=true`
`not_atlas_primary_thought=true`

Regra:

- o subagente pode decidir passos internos do browser;
- o subagente nao pode decidir tool choice global;
- o subagente nao pode escrever resposta final ao usuário;
- o subagente nao pode converter pensamento narrativo em autoridade semântica do Atlas.

## 3. Contrato mínimo

O contrato interno do subagente deve poder representar, no mínimo:

- `browser_thought`: texto diagnóstico ou memória interna do browser;
- `browser_plan`: plano interno do browser;
- `browser_step`: estado estruturado do passo atual;
- `completion_signal`: sinal estruturado de conclusão, parcialidade, bloqueio ou falha;
- `planner_diagnostic`: diagnóstico técnico de parse, fallback e replan;
- `next_action`: próxima ação operacional.

Exemplo:

```json
{
  "source": "browser_control",
  "agent_role": "subagent",
  "semantic_authority": "internal_browser_only",
  "not_user_facing": true,
  "not_atlas_primary_thought": true,
  "browser_thought": "search results visible, continue to compare candidates",
  "browser_plan": [
    {"step_id": "1", "text": "open page", "status": "done"},
    {"step_id": "2", "text": "search target", "status": "current"}
  ],
  "browser_step": {
    "current_step_index": 1,
    "completed_step_index": 0,
    "next_step_index": 1,
    "step_status": "in_progress"
  },
  "completion_signal": {
    "status": "partial",
    "reason": "results_visible_but_not_verified",
    "milestone_id": "search_results_visible",
    "evidence": [
      {"kind": "dom", "signal": "results list visible"}
    ]
  },
  "planner_diagnostic": {
    "parse_status": "ok",
    "planner_error": null,
    "fallback_reason": null,
    "requires_replan": false,
    "blocked_reason": null
  },
  "next_action": {
    "action": "click",
    "args": {"id": "node_42"}
  }
}
```

## 4. Regra principal

Texto narrativo de pensamento é diagnóstico, nao controle de fluxo.

O fluxo deve depender de campos estruturados:

- `completion_signal.status`;
- `completion_signal.completed_step_index`;
- `browser_step.current_step_index`;
- `browser_step.completed_step_index`;
- `browser_step.next_step_index`;
- `browser_step.step_status`;
- `planner_diagnostic.parse_status`;
- `planner_diagnostic.requires_replan`;
- `next_action`.

## 5. Mapping de legado para o novo contrato

| Legado | Novo contrato |
|---|---|
| `thought` | `browser_thought` |
| `self._plan` | `browser_plan` |
| `self._current_step_idx` | `browser_step.current_step_index` |
| `self._sticky_completed_idx` | `browser_step.completed_step_index` |
| `action` | `next_action.action` |
| `args` | `next_action.args` |
| parse failures | `planner_diagnostic` |
| validation context | `evidence` / `browser_validation_context` |

## 6. Migração segura

1. adicionar campos estruturados sem remover `thought`;
2. preencher novos campos junto do formato atual;
3. fazer `_apply_sticky_progress()` preferir `completion_signal` e `browser_step`;
4. manter `thought_lower` apenas como fallback legado temporário com warning e diagnóstico;
5. adicionar testes;
6. remover string matching depois da estabilização.

## 7. Testes esperados

- completion signal avança step sem ler thought;
- thought textual sozinho nao avança step;
- invalid_json entra em planner_diagnostic;
- browser_thought nao entra em chat nem em thoughts primários do Atlas;
- run_report persiste `browser_step`, `completion_signal` e `planner_diagnostic`;
- history continua interno ao browser.

## 8. Fora do escopo

Esta spec nao altera:

- prompt principal do Atlas;
- LLMResolver;
- providers;
- sessions/events;
- frontend;
- tool choice global;
- policies agenticas.

## Relacionados

- [browser-subagent-internal-contract.stat.md](browser-subagent-internal-contract.stat.md)
- [atlas_operating_model.spec.md](atlas_operating_model.spec.md)
- [semantic_decision_boundary.spec.md](semantic_decision_boundary.spec.md)
- [../README.md](../overview.md)
