# Spec / Stat Policy

- `agent/specs/` e a fonte canônica das specs normativas do agente e do sistema;
- `docs/` e documentação humana, explicativa e operacional, podendo apontar para specs mas nao substitui-las;
- `.spec` é contrato durável;
- `.stat` é estado vivo;
- toda `.spec` ativa deve ter `.stat`;
- `.spec` não registra progresso;
- `.stat` não redefine contrato;
- specs precisam ter domínio claro;
- spec genérica demais deve ser dividida;
- atualize `.spec` quando contrato mudar;
- atualize `.stat` quando o estado mudar.
