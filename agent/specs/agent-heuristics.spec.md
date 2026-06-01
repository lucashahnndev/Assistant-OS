# Agent Heuristics Spec

Data: 2026-05-27

## Propósito

Este documento define como o Atlas deve usar heuristicas sem transformar a arquitetura em uma camada que controla rigidamente o comportamento do agente.
O comportamento operacional do agente e o papel do runtime estão definidos em [atlas_operating_model.spec.md](atlas_operating_model.spec.md).

O objetivo e:

- preservar autonomia agentica real
- garantir contratos estaveis entre componentes
- manter segurança, observabilidade e integridade
- permitir adaptação por interface, transporte e ACL
- evitar hardcode de comportamento por cenário

## O que este documento e

Este spec e um acordo de limites.

Ele descreve:

- o que a arquitetura pode impor
- o que ela deve apenas sugerir
- o que deve variar por interface
- o que nunca deve ser hardcoded como raciocinio fixo

## O que este documento nao e

Este spec nao e:

- um mapa de `if/else` para decidir o proximo passo do agente
- um manual para forcar respostas por caso de uso
- um substituto do planner, do LLM ou do orchestrator
- um lugar para ensinar a personalidade do agente por excecao

## Principios

### 1. A arquitetura protege, nao pensa pelo agente

A arquitetura deve validar, normalizar, registrar e limitar. Ela nao deve escolher o raciocinio do agente quando existir alternativa de contrato.

### 2. Heuristica orienta, nao ordena

Hints, scores, prioridades e sinais de contexto devem influenciar a decisao, mas nao substituir a decisao do agente.

### 3. Contrato acima de interpretacao

Se uma saida ou estado viola o contrato, a arquitetura deve corrigir ou rejeitar. Se apenas sugere algo, a arquitetura deve registrar e encaminhar, nao impor.

### 4. Variacao por interface e permitida

Web, voz, Telegram, desktop e outros canais podem mudar:

- formato da resposta
- densidade de contexto
- tipo de confirmacao
- nivel de detalhe visual
- tom de exibicao

Essas variacoes pertencem a camada de adaptacao, nao a camada de raciocinio.

### 5. Roteamento deve ser fino

Os drivers, transportes e interfaces devem depender o minimo possivel de roteamento central para decidir comportamento.

O roteamento deve:

- adaptar envelope
- escolher formato
- aplicar ACL
- registrar observabilidade
- preparar contexto

O roteamento nao deve:

- pensar pelo agente
- impor uma unica trilha cognitiva
- codificar excecoes de dominio como regra de negocio fixa
- substituir planner, LLM ou orchestrator

## Invariantes duras

Estas regras sao obrigatorias:

- nao afirmar execucao sem prova de dispatch
- nao aceitar memoria rejeitada como memoria aceita
- nao tratar resultado parcial como sucesso pleno
- nao deixar allowlist vazia virar permissao
- nao suprimir evento valido por dedupe errado
- nao colapsar fallback generico em sucesso sem semantica
- nao transformar telemetria em verdade de produto quando ela e apenas indicativa

## Heuristicas permitidas

Heuristicas podem ser usadas para:

- priorizacao de contextos
- sugestao de tools relevantes
- reorganizacao de evidencia
- reducao de ruido
- escolha de formato por canal
- adaptacao de UX por estado

Essas heuristicas devem ser:

- configuraveis quando possivel
- observaveis quando aplicadas
- reversiveis quando gerarem ruido
- testadas com regressao

## Regras de uso de `if`

Condicionais sao permitidas quando servem a:

- seguranca
- renderizacao
- adaptacao de transporte
- ACL
- validacao de contrato
- observabilidade

Condicionais sao arriscadas quando:

- tentam decidir comportamento cognitivo por cenário
- codificam excecoes de dominio como se fossem lei universal
- assumem a proxima acao do agente
- mascaram a falta de contrato ou telemetria

## Adaptacao por interface

### Web

Pode priorizar:

- cards
- resumo visual
- status de execucao
- sinais de progresso

### Voz

Pode priorizar:

- respostas curtas
- confirmacoes claras
- menos ruido visual
- pausas e retries controlados

### Telegram

Pode priorizar:

- mensagens compactas
- comandos claros
- links diretos
- confirmacao textual objetiva

### Desktop

Pode priorizar:

- contexto mais rico
- configuracoes avancadas
- visibilidade de logs
- controles operacionais

## Heuristicas de contexto

O contexto deve ser apresentado ao agente como sinal, nao como ordem.

Exemplos de sinais validos:

- `signal_strength`
- `approval_pending`
- `troubleshooting_active`
- `primary_task_id`
- `hot_action_namespace`
- `hint_summary`
- `hint_categories`

Esses sinais podem:

- mudar prioridade
- alterar foco
- ativar um dominio de recuperacao
- reforcar ou reduzir evidencia

Eles nao devem:

- forcar uma unica resposta
- bloquear autonomia sem contrato
- substituir o planner

## Fronteira semantica

Heuristicas nao podem virar decisao final de significado.

Em particular:

- keyword matching nao deve ser tratado como verdade semantica;
- regex nao deve substituir interpretacao do LLM;
- hints nao devem ser promovidos a decisao final sem contrato explicito;
- o agente continua responsavel pela decisao semantica, enquanto a arquitetura apenas apoia, limita e registra.

## MCP e ferramentas externas

O suporte a MCP deve obedecer a mesma logica:

- discovery e permitido
- roteamento interno deve ser minimo
- execucao deve respeitar contrato e policy
- tools externas nao devem virar hardcode de fluxo
- recursos externos devem entrar como evidencia, nao como verdade absoluta

## Antipadroes proibidos

Nao devemos:

- criar `if` por caso de usuario para controlar o raciocinio do agente
- hardcodar respostas por interface sem necessidade de contrato
- usar telemetria como se fosse verdade final
- esconder falha por resposta cosmetica
- misturar heuristica com regra dura sem rotulo claro
- transformar fallback em sucesso aparente

## Critérios de aceitação

Uma heuristica esta aceitavel quando:

- melhora o contrato ou a UX sem limitar o agente de forma indevida
## Relacionados

- [agent-heuristics.stat.md](agent-heuristics.stat.md)
- [../README.md](../overview.md)
