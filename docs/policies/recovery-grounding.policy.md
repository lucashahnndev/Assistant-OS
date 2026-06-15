# Recovery Grounding Policy

Data: 2026-05-28

## Propósito

Esta policy define como a resposta de recovery deve se comportar quando o runtime ainda nao confirmou execucao real de uma ação.

## Regra principal

Nao afirmar que uma acao foi iniciada, executada ou concluida sem evidencia real de ferramenta, status de approval ou resultado de ferramenta.

## Quando faltar evidência

Quando nao houver tool output, approval ativo ou plano em execucao:

- mantenha a resposta neutra;
- explique o bloqueio de forma curta;
- solicite apenas o contexto minimo necessario para seguir;
- nao use frases como "estou tentando", "iniciei" ou "ja comecei" como substituto de evidência.

## Quando houver approval pendente

Se a acao depender de approval, a resposta deve:

- mencionar que a execucao aguarda aprovacao;
- evitar simular inicio de execucao;
- evitar concluir que o trabalho avancou antes do sinal do runtime.

## Quando houver evidência real

Se houver evidence de ferramenta ou estado validado, a resposta pode resumir o resultado de forma conversacional, sem exagerar no fechamento.

## Fecho

Recovery e linguagem de apoio.
Evidência e runtime.
Nao misturar os dois.

## Relacionados

- [../overview.md](../overview.md): indice geral da documentacao humana.
- [../guides/testing_guide.md](../guides/testing_guide.md): guia para validar fluxos de recovery e continuidade.
- [../reports/atlas-agent-mode-cognition-deep-audit-2026-05-29.md](../reports/atlas-agent-mode-cognition-deep-audit-2026-05-29.md): audit que explica os riscos de fallback narrativo.
- [../reports/system-audit-2026-05-24.md](../reports/system-audit-2026-05-24.md): audit de base sobre estado, browser e fluxos.
