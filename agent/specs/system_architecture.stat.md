# System Architecture Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- arquitetura base formalizada em spec;
- camadas Kernel, Drivers, Orchestrator e Memory continuam como contrato central;
- o portal HTML de arquitetura agora aponta para a pasta `docs/architecture/`.
- a descrição de reflexes foi atualizada para nao normalizar regex hardcoded como autoridade semantica.

## Pendencias

- manter alinhamento entre runtime real e descricao arquitetural;
- revisar documentos filiados quando camadas novas forem introduzidas.
- referenciar a nova spec de fronteira semantica quando o fluxo cognitivo for reavaliado.

## Evidencias / validacoes

- indice da pasta criado;
- spec movida para a pasta de arquitetura;
- referencias antigas ainda estao sendo normalizadas.

## Proximo passo recomendado

- usar esta spec como referencia para revisar docs secundarias de arquitetura.
- usar `semantic_decision_boundary.spec.md` como clausula de fronteira semantica principal.
