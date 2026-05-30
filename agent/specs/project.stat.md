# Project Stat

Data da última atualização: 2026-05-28

Este é o estado inicial pareado com `project.spec.md`.

## Estado atual

- convenção inicial criada;
- estrutura base disponível;
- domínios reais ainda podem ser separados em specs próprias.
- artefatos temporarios de validacao foram movidos para `agent/test/` e `agent/scripts/`, reduzindo o uso de `tests/` e `scratch/` para apoio operacional fora da workspace do agente.

## Pendências

- definir specs de domínio reais quando o projeto alvo amadurecer;
- ajustar documentação operacional conforme o uso concreto aparecer.

## Evidências / validações

- template inicial criado;
- estrutura do workspace definida;
- convenção de `.spec` e `.stat` estabelecida.
- a raiz do repositorio foi limpa de scripts e arquivos de teste temporarios rastreados; os artefatos pontuais de validacao agora vivem na workspace do agente.

## Próximo passo recomendado

- substituir ou dividir esta spec fundacional quando os domínios do projeto estiverem claros.

## Riscos ou dúvidas abertas

- esta spec é apenas um ponto de partida;
- não deve absorver domínios independentes por conveniência.

## Regra central

- `.stat` registra estado, pendências, validações e próximos passos.
- `.stat` não redefine contrato.

## Registros de commits recentes

- `fa7b13dc` `chore: move temporary validation assets into agent workspace`
  - resumo: moveu harnesses temporarios de `tests/minimal/` para `agent/test/` e scripts de `scratch/` para `agent/scripts/`, reduzindo sujeira fora da workspace do agente;
  - validacao: `python3 -m py_compile agent/scripts/check_braces.py agent/scripts/check_syntax.py agent/test/test_attachment_delivery_contract.py agent/test/test_last_mile_grounding.py agent/test/test_observation_freshness.py agent/test/test_orchestrator_grounding_flow.py` e `PYTHONPATH=src:. env/bin/python -m pytest agent/test/test_attachment_delivery_contract.py agent/test/test_last_mile_grounding.py agent/test/test_observation_freshness.py agent/test/test_orchestrator_grounding_flow.py -q`;
  - falhas conhecidas fora do escopo: os arquivos paralelos de frontend e os testes antigos de alias/Obsidian continuam fora desta limpeza e nao foram alterados.
