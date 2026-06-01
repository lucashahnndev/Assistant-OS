# Planner: Auditoria e Correção de Skills

## Objetivo
Validar e corrigir o stack de skills ponta-a-ponta, cobrindo:
- contrato (`contract.json`) x runtime (registry),
- parâmetros de entrada,
- formato de saída amigável para IA (`ok/status/text/results`),
- confiabilidade funcional (shell, browser, busca web/música, system, memory, logs, weather).

## Estado Atual (auditado)
- Ações registradas no runtime: **44**
- Ações declaradas nos contratos: **44**
- Divergências contrato x registry: **0**
- Fonte da checagem: `SkillLoader + SkillRegistry` com varredura completa em `src/skills/*`.

## Correções já aplicadas (nesta etapa)
1. Alinhamento contrato x namespace/runtime:
- `src/skills/shell_control/contract.json`
- `src/skills/system_apps/contract.json`
- `src/skills/system_control/contract.json`
- `src/skills/weather_control/contract.json`
- `src/skills/browser_automator/contract.json` (inclui `navigate`)

2. Saída estruturada e fallback resiliente:
- `src/skills/web_search/skill.py`
- `src/skills/youtube_search/skill.py`
- `src/skills/deezer_search/skill.py`
- `src/skills/spotify_search/skill.py`
- `src/skills/shell_control/skill.py`
- `src/skills/browser_automator/skill.py`
- `src/skills/weather_control/skill.py` (inclui previsão)
- `src/skills/memory_management/skill.py`
- `src/skills/system_logs/skill.py`
- `src/skills/system_apps/skill.py`
- `src/skills/system_control/skill.py`
- `src/skills/vision/skill.py`
- `src/skills/maps_search/skill.py` (cidade + modo diversificado + filtros)

3. Compatibilidade de controle de mídia no browser:
- `src/drivers/browser_driver.py` (`mute` suportado)

4. Redução de redundância reflex:
- Regras reflex (`/status`, `/cancel`) migradas para `system_control`.
- `reflex_skill` mantido como alias legado de compatibilidade.

5. Documentação de contrato atualizada:
- `agent/specs/skill_contract.spec.md`

6. Contratos com parâmetros explícitos (coverage de `params.get(...)`):
- `src/skills/system_apps/contract.json`
- `src/skills/system_control/contract.json`
- `src/skills/vision/contract.json` (`file_path` alias)
- `src/skills/maps_search/contract.json` (city/category/diverse/open_now/min_rating/etc)

7. Descrições para UX Web revisadas:
- Contratos atualizados com descrições mais claras (skills e actions) para exibição no Skills Hub e telas de permissão.

8. Cobertura de testes adicionada:
- `tests/test_skills_quality.py`

## Achados pendentes (prioridade)
### Alta
- `src/skills/task_management/skill.py` e `src/skills/reflex_skill/skill.py`
  - retornos não uniformes (strings soltas) e baixa semântica para LLM.

### Média
- `src/skills/vision/skill.py`
  - revisar envelopes em integrações reais com diferentes providers de LLM (hardening).

### Baixa
- Expandir testes E2E de browser/shell em ambiente gráfico real (não apenas unitário).

## Plano de execução
### F1 - Padronização de envelope (Core skills)
- Normalizar saída de `task_management` e consolidar comportamento legado de `reflex_skill`.
- Contrato mínimo de resposta:
  - `ok: bool`
  - `status: success|empty|error`
  - `error` e `message` (quando aplicável)
  - `text` (resumo para LLM)
  - `results/best/count` quando houver listagem

### F2 - Contrato de parâmetros
- Revisar `parameters/params` em `contract.json` para cada ação.
- Garantir que parâmetros usados em `params.get(...)` estejam documentados no contrato.

### F3 - Robustez operacional
- Validar cenários reais de `maps_search` com API key habilitada + billing (diverse mode, geocode, filtros).

### F4 - Testes por skill
- Adicionar testes unitários por skill (sucesso/erro/fallback).
- Adicionar smoke tests de integração para ações críticas.

### F5 - Validação E2E
- Cenários reais:
  - shell command + parse de saída,
  - browser automate/open/control,
  - web/youtube/deezer/spotify busca com e sem credenciais,
  - weather atual + forecast,
  - memory/logs/system flows.

## Critérios de pronto
- 100% das ações registradas possuem contrato coerente e parâmetros declarados.
- 100% das skills críticas retornam payload estruturado (sem string solta em erro crítico).
- Weather com previsão operacional (`weather.control.forecast`) via OpenWeather e fallback.
- Testes de skill stack verdes para fluxos principais.

## Relacionados

- [../policies/README.md](../policies/README.md): politicas de governanca e documentacao que cercam a auditoria.
- [../reports/README.md](../reports/README.md): saida natural das auditorias e evidencias.
- [../../agent/specs/skill_contract.spec.md](../../agent/specs/skill_contract.spec.md): contrato normativo das skills.
- [../../agent/specs/README.md](../../agent/specs/README.md): indice canônico dos contratos normativos do agente.
