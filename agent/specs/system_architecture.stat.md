# System Architecture Stat

Data da ultima atualizacao: 2026-05-30

## Estado atual

- arquitetura base formalizada em spec;
- camadas Kernel, Drivers, Orchestrator e Memory continuam como contrato central;
- o portal HTML de arquitetura agora aponta para a pasta `docs/architecture/`.
- a descrição de reflexes foi atualizada para nao normalizar regex hardcoded como autoridade semantica.
- o runtime passou a registrar um envelope estruturado de observacao pos-execucao, mantendo a observacao textual compativel para o proximo ciclo do agente.
- o envelope de observacao agora projeta evidencia enumeravel fiel quando o output estruturado traz listas/itens/campos exatos, preservando preview/truncamento explicitos para o proximo ciclo.
- a nova spec `atlas_operating_model.spec.md` passou a servir como referencia operacional para clarificar que o agente opera sobre um runtime com gates tecnicos.

## Pendencias

- manter alinhamento entre runtime real e descricao arquitetural;
- revisar documentos filiados quando camadas novas forem introduzidas.
- referenciar a nova spec de fronteira semantica quando o fluxo cognitivo for reavaliado.
- acompanhar a nova observacao estruturada no loop para garantir que o proximo passo do agente leia o estado de forma mais explicita.

## Evidencias / validacoes

- indice da pasta criado;
- spec movida para a pasta de arquitetura;
- referencias antigas ainda estao sendo normalizadas.
- observacao textual antiga continua existindo, mas agora ha um envelope estruturado em `session.context` e um resumo compacto em `state_summary`.
- outputs enumeraveis agora carregam `evidence_items`/`last_observation_evidence` para grounding mais fiel sem inflar o contexto bruto.

## Proximo passo recomendado

- usar esta spec como referencia para revisar docs secundarias de arquitetura.
- usar `semantic_decision_boundary.spec.md` como clausula de fronteira semantica principal.
- usar `atlas_operating_model.spec.md` como clausula operacional principal para clarificar papel do agente, do runtime e da clarificacao.
