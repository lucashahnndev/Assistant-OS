# Spec / Stat Policy

- `.spec` é contrato durável;
- `.stat` é estado vivo;
- toda `.spec` ativa deve ter `.stat`;
- `agent/specs/` concentra os contratos normativos que orientam mudanças no projeto;
- `docs/` pode referenciar specs, mas não substitui `agent/specs/` como fonte principal de contrato;
- `.stat` não substitui Git, mas pode referenciar hash, mensagem e resumo do commit para rastreabilidade;
- `.spec` não registra progresso;
- `.stat` não redefine contrato;
- specs precisam ter domínio claro;
- spec genérica demais deve ser dividida;
- atualize `.spec` quando contrato mudar;
- atualize `.stat` quando o estado mudar.

## Relacionados

- [../specs/README.md](../specs/overview.md)
- [../specs/project.spec.md](../specs/project.spec.md)
- [../specs/project.stat.md](../specs/project.stat.md)
- [linking.policy.md](linking.policy.md)
