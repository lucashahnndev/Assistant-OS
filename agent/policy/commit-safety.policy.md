# Commit Safety Policy

- rode `git status --short` antes de propor ou fazer commit;
- revise o diff;
- se o projeto usa Git, mudanças relevantes devem terminar com `.stat` atualizada; quando aprovado, devem terminar também com commit limpo e coerente; a `.stat` deve registrar hash, mensagem e resumo do commit; se o commit não for feito, a `.stat` deve registrar o motivo;
- não misture no commit arquivos fora do escopo da etapa;
- não commite segredos, `.env`, dumps, snapshots ou logs sensíveis;
- não commite temporários por acidente;
- prefira commits pequenos por etapa;
- se necessário, separe mudança de contrato, implementação e limpeza.
