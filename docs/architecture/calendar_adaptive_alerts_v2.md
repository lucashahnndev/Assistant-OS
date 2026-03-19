# Calendar Adaptive Alerts v2 (WHEN + WHERE + HOW)

## Resumo Executivo
Esta revisão amplia a proposta anterior (focada principalmente em **WHEN**) para um modelo tridimensional e supervisionado:
- **WHEN**: quando alertar.
- **WHERE**: onde entregar (sessão ativa, push, fila pendente, canais futuros).
- **HOW**: como formular e inserir a notificação (tom, formato, grau de interrupção).

O que mudou em relação à proposta anterior:
- introdução explícita de **interruptibility** como variável central de decisão;
- separação clara entre política de tempo, política de canal e política de estilo;
- integração estruturada com memória/RAG para aprendizado auditável;
- governança mais rígida para autoajustes e mudanças com risco de spam/invasividade.

Por que a v2 é melhor:
- reduz comportamento “one-size-fits-all” sem perder previsibilidade;
- melhora utilidade prática (chegar no canal certo, com forma certa, no momento certo);
- mantém rastreabilidade e reversão de decisões.

Trade-offs:
- maior complexidade operacional e de observabilidade;
- necessidade de pipeline de sinais mais maduro;
- rollout necessariamente gradual para evitar drift comportamental.

---

## 1) Diagnóstico da Proposta Atual

A proposta atual já acerta fundamentos críticos:
- núcleo determinístico no caminho crítico;
- camada adaptativa separada (observer propondo patch);
- delivery desacoplado;
- guardrails e auditabilidade como princípios.

### 1.1 O que já está coberto
- **Timing adaptativo (WHEN)**:
  - já existe o conceito de offsets base + ajuste por política;
  - fallback determinístico (`30/10/1`) em ausência de evidência.
- **Canal adaptativo (WHERE)**:
  - existe noção de estratégia de entrega (sessão ativa preferida vs push);
  - já há dedupe e fallback no roteamento.
- **Forma/estilo (HOW)**:
  - existe caminho para intenção estruturada e renderização por persona;
  - porém a política de estilo ainda não está modelada como eixo explícito.

### 1.2 O que ainda está implícito/insuficiente
- canal ainda pouco modelado por contexto/efeito histórico;
- estilo de mensagem sem policy versionada dedicada;
- falta variável explícita de **interruptibility** orientando WHEN/WHERE/HOW;
- aprendizado via memória/RAG sem contrato específico para “preferências de notificação”;
- ausência de governança detalhada para mudanças automáticas por eixo.

---

## 2) Lacunas e Riscos Atuais

Lacunas principais:
- adaptação concentrada em tempo, subexplorando canal e estilo;
- baixa explicabilidade fina do “por que foi nesse canal e nesse tom”;
- risco de regressão para mensagens hardcoded em bordas de delivery;
- risco de aprendizado incorreto por sinais implícitos ruidosos.

Riscos se expandir sem controle:
- spam por escalonamento excessivo de push;
- invasividade em horários/contextos inadequados;
- drift de persona e inconsistência de experiência;
- perda de confiança do usuário por mudanças não transparentes.

---

## 3) Arquitetura Revisada (v2)

## 3.1 Princípios
- caminho crítico permanece determinístico;
- adaptação entra como **policy input supervisionado**, nunca execução direta irrestrita;
- cada decisão deve ser explicável com evidência e versão de política;
- decisões com maior impacto exigem aprovação explícita.

## 3.2 Topologia v2 (alto nível)
`CalendarEvent -> AlertPolicyEngine -> NotificationOrchestrator -> DeliveryRouter -> NotificationDispatcher -> FeedbackCollector -> AdaptivePolicyObserver -> PolicyStore + PolicyPatchPipeline`

Complemento de contexto:
`FeedbackCollector -> LearningSignalStore -> Memory/RAG (typed) -> AdaptivePolicyObserver`

## 3.3 Fronteira de responsabilidades (revisada)

### AlertPolicyEngine (determinístico)
Gera um **notification_plan** por evento com três eixos:
- timing policy (WHEN);
- channel policy (WHERE);
- style policy (HOW);
- interruptibility target (`low|medium|high`).

Não envia nada diretamente; apenas decide plano e restrições.

### NotificationOrchestrator
Coordena execução do plano no tempo:
- ativa triggers no momento correto;
- faz gate de guardrails globais/usuário;
- resolve se entrega é `aside` (sessão ativa) ou `outreach` (push/externo) conforme interruptibility + política;
- emite intenção estruturada para roteamento.

### DeliveryRouter
Escolhe destino concreto e ordem de tentativa:
- sessão ativa por interface;
- push elegível;
- fila pendente.

Aplica policy de canal, estado de presença e disponibilidade de interface.

### NotificationDispatcher
Executa envio técnico por interface, com:
- dedupe técnico;
- retry/backoff;
- marcação de resultado de entrega.

Não decide estratégia; apenas entrega conforme decisão anterior.

### AdaptivePolicyObserver (agentic supervisionado)
Analisa sinais e propõe patches de política por eixo WHEN/WHERE/HOW, com:
- score de confiança;
- impacto estimado;
- risco e necessidade de aprovação.

Nunca bypassa `AlertPolicyEngine` nem dispara envio direto.

---

## 4) Modelo de Política por Dimensão

## 4.1 Timing Policy (WHEN)
Objetivo: otimizar antecedência e cadência.

Exemplos de parâmetros:
- offsets por classe de evento (`[45, 10, 0]`, `[20, 5, 0]` etc.);
- quiet-hour behavior (`hold`, `digest`, `critical-only`);
- janelas de cooldown entre alertas.

Sinais principais:
- response latency pós-alerta;
- taxa de ignorar/snooze por offset;
- confirmação explícita de utilidade do lembrete.

## 4.2 Channel Policy (WHERE)
Objetivo: escolher canal com maior efetividade e menor fricção.

Exemplos de parâmetros:
- preferência por contexto (`web_active_preferred`, `telegram_if_inactive`);
- regras por criticidade/event_type;
- limite de escalonamento para push.

Sinais principais:
- taxa de abertura/resposta por canal;
- taxa de falha/atraso de entrega por canal;
- mudanças manuais de canal pelo usuário.

## 4.3 Delivery Style Policy (HOW)
Objetivo: ajustar forma/tom para maximizar compreensão e ação.

Exemplos de parâmetros:
- estilo base: `short`, `contextual`, `directive`, `gentle`;
- modo em sessão ativa: `aside` vs `full-turn`;
- estratégia de pergunta antes de agir (`ask_before_change`).

Sinais principais:
- engajamento após estilo A/B;
- pedidos de reformulação (“seja mais direto”, “resuma”);
- confirmações explícitas de preferência de tom.

---

## 5) Interruptibility (variável transversal)

Definição proposta:
- `interruptibility=low`: não interromper fluxo ativo; preferir aside discreto ou hold.
- `interruptibility=medium`: pode interromper em sessão ativa; push com parcimônia.
- `interruptibility=high`: permite outreach/push imediato (respeitando guardrails críticos).

`interruptibility` influencia simultaneamente:
- **WHEN**: tolerância a atraso/hold;
- **WHERE**: permissão de escalonamento de canal;
- **HOW**: forma de inserção (aside/outreach) e tom.

Heurísticas base (determinísticas):
- evento crítico + sem sessão ativa -> eleva interruptibility;
- conversa ativa sensível + evento de baixa urgência -> reduz interruptibility;
- quiet-hours -> reduz interruptibility salvo exceções explícitas.

---

## 6) Uso de Memória/RAG (Aprendizado Auditável)

## 6.1 Princípio de integração
Memória/RAG deve **informar política**, não substituir enforcement determinístico.

## 6.2 Estrutura recomendada de conhecimento
Adicionar domínio tipado de aprendizado de notificações (ex.: `notification_adaptation_memory`), com entradas curtas e auditáveis:
- contexto resumido do evento;
- decisão tomada (WHEN/WHERE/HOW + interruptibility);
- resultado observado;
- confiança do sinal;
- referência de policy/version.

Metadados mínimos por item:
- `user_id`, `event_type`, `channel`, `style`, `offset`, `interruptibility`;
- `outcome` (`responded`, `ignored`, `snoozed`, `dismissed` etc.);
- `decision_trace_id`, `policy_version`, `timestamp`.

## 6.3 Pipeline de aprendizado
1. FeedbackCollector captura sinais explícitos/implícitos.
2. LearningSignalStore normaliza e pontua qualidade do sinal.
3. Ingestão para memória tipada (com dedupe e janela temporal).
4. AdaptivePolicyObserver recupera evidências relevantes (RAG) por contexto.
5. Observer propõe patch com justificativa e confiança.
6. PolicyPatchPipeline valida guardrails e decide auto-apply vs aprovação.

## 6.4 Proteções contra “aprendizado errado”
- threshold mínimo de evidência por tipo de ajuste;
- decaimento temporal (recency) para evitar viés antigo;
- limiar de confiança + coerência entre sinais explícitos/implícitos;
- canary rollout antes de promoção global.

---

## 7) Guardrails e Limites de Adaptatividade

## 7.1 Pode adaptar automaticamente (baixo risco)
- microajustes de offsets dentro de faixa segura;
- preferência de canal secundário em contextos específicos;
- estilo de redação entre presets aprovados;
- escolha `aside` vs `full-turn` em sessão ativa para baixa/média urgência.

## 7.2 Exige aprovação explícita (médio/alto risco)
- mudança de canal principal padrão;
- push em quiet-hours fora exceções;
- aumento de agressividade de interrupção;
- escalonamento de push em eventos antes tratados como discretos;
- qualquer alteração que eleve potencial de spam.

## 7.3 Controles operacionais obrigatórios
- dedupe por `event_id + stage + channel + time_bucket`;
- rate limit por usuário e por canal;
- limite diário de outreach ativo;
- rollback imediato por versão de política.

---

## 8) Métricas e Sinais de Efetividade

Sinais base:
- `ignore_rate`, `dismiss_rate`, `snooze_rate`;
- `response_latency`;
- `engagement_after_alert` (resposta, abertura, ação subsequente);
- `reopen_or_reply_rate` após alerta;
- ajustes manuais de canal/horário pelo usuário;
- confirmação explícita de preferência.

Impacto por eixo:
- **WHEN**: melhora quando reduz `ignore_rate` e `response_latency` sem elevar spam.
- **WHERE**: melhora quando aumenta engajamento por canal com menor fricção.
- **HOW**: melhora quando aumenta compreensão/ação e reduz reformulação.

KPIs de governança:
- taxa de rollback de patches;
- taxa de patches aprovados vs rejeitados;
- estabilidade de política (evitar oscilação excessiva);
- explicabilidade (percentual de decisões com trace completo).

---

## 9) Rollout por Fases

### Fase 0 — Base determinística robusta
- consolidar plano `WHEN/WHERE/HOW` ainda estático;
- padronizar decision trace e dedupe/rate limit.

### Fase 1 — Adaptativo de timing (WHEN)
- ativar observer só para offsets;
- modo recomendação + aprovação manual inicial.

### Fase 2 — Adaptativo de canal (WHERE)
- aprender preferência por contexto/presença;
- autoapply apenas em ajustes de baixo risco.

### Fase 3 — Adaptativo de estilo (HOW)
- presets de estilo aprovados;
- seleção contextual supervisionada com guardrails.

### Fase 4 — Interruptibility unificada
- interruptibility vira variável primária em todas decisões;
- validação forte de impacto em spam/invasividade.

### Fase 5 — Aprendizado supervisionado com memória/RAG
- ingestão contínua de sinais auditáveis;
- policy patches com confiança, risco e canary rollout.

### Fase 6 — Governança plena
- auditoria completa de ponta a ponta;
- rollback automatizado por degradação de KPI;
- explicações operacionais disponíveis por decisão.

---

## 10) Componentes Revisados (Detalhamento)

### AlertPolicyEngine
- novo contrato obrigatório com `timing_policy`, `channel_policy`, `style_policy`, `interruptibility`.

### EventObserver -> AdaptivePolicyObserver
- evolução semântica para cobrir 3 eixos e risco por patch.

### FeedbackCollector
- ampliar para sinais de canal/estilo e qualidade do engajamento.

### NotificationOrchestrator vs DeliveryRouter (fronteira final)
- `NotificationOrchestrator`: decide estratégia de execução e modo de interrupção.
- `DeliveryRouter`: resolve destino concreto conforme estratégia.
- `NotificationDispatcher`: entrega técnica e telemetria de sucesso/falha.

### PolicyStore
- versionamento por eixo e escopo (`global`, `user`, `event_class`);
- suporte a histórico de patch, aprovação e rollback.

### Novo: PolicyPatchPipeline
- valida patch (schema + risco + guardrails);
- aplica canary, monitora KPI, promove ou reverte.

### Novo: LearningSignalStore
- camada de normalização e confiança de sinal antes do observer.

---

## 11) Governança e Auditabilidade

Cada notificação deve possuir `decision_trace` mínimo:
- contexto de entrada relevante;
- policy version aplicada por eixo;
- decisão WHEN/WHERE/HOW + interruptibility;
- razão resumida e evidências usadas;
- resultado de entrega e reação observada.

Auditoria operacional:
- trilha de patches (`proposed -> approved/rejected -> applied -> rolled_back`);
- explicação legível para “por que foi enviado assim”;
- detecção de drift por variação anômala de comportamento;
- playbook de reversão por escopo (usuário, classe de evento, global).

---

## 12) Recomendações Finais
- adotar v2 com rollout progressivo e métricas de segurança desde o início;
- priorizar primeiro a qualidade de sinais (telemetria + normalização) antes de ampliar autoapply;
- manter persona flexível no texto final, mas com política de estilo explícita e versionada;
- tratar interruptibility como contrato central para evitar spam e melhorar experiência;
- manter memória/RAG como suporte explicável de decisão, nunca como executor opaco.

