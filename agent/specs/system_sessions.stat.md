# System Sessions Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- isolamento de sessoes de dominio formalizado em spec;
- fluxo de eventos internos e sessao `system.<domain>` descritos;
- a documentacao ainda precisa de alinhamento fino com a implementacao final.

## Pendencias

- validar que o comportamento real de `is_internal=True` e `silent=True` permanece coerente;
- manter a regua de indexacao e visibilidade da UI alinhada ao codigo.

## Evidencias / validacoes

- documento movido para `.spec`;
- use case de isolamento de dominio mantido como contrato duravel.

## Proximo passo recomendado

- revisar docs adjacentes de eventos e trusted path quando o modelo de sessao evoluir.
