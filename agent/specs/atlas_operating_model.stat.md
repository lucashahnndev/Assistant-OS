# Atlas Operating Model Stat

Data da ultima atualizacao: 2026-05-30

## Estado atual

- nova spec operacional criada para explicitar que o agente e operador e o runtime e gatekeeper;
- o modelo operacional reforca a fronteira entre clarificacao util e clarificacao como fuga;
- a resposta deve permanecer grounded em evidência real, inclusive em outputs enumeraveis;
- ActionObservation agora carrega proveniencia e freshness explicitas para diferenciar observacao atual de memoria ou resumo antigo;
- ferramentas sao escolhidas pelo agente e validadas pelo runtime.

## Pendencias

- usar esta spec como referencia de leitura para prompt, discovery e future agents;
- alinhar documentos correlatos para citar este contrato quando o comportamento operacional for reavaliado.

## Evidencias / validacoes

- spec criada em `agent/specs/`;
- boundary documental agora tem uma fonte operacional explicita para o comportamento do agente.

## Proximo passo recomendado

- revisar o prompt composer para refletir esta regra sem reintroduzir cautela genérica ou clarificação defensiva;
- manter a regra de freshness para evitar que observacoes antigas sejam tratadas como prova atual;
- manter approval e safety como responsabilidade do runtime, nao do medo do agente.
