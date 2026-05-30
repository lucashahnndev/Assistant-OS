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
