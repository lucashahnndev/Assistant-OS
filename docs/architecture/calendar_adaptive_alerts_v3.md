# Calendar Adaptive Alerts v3 (Preference-First + Confidence-Governed Learning)

## Resumo Executivo
A v3 evolui a v2 com duas camadas críticas:
- **UserPreferenceLayer**: preferências explícitas do usuário como restrições de maior autoridade.
- **SignalConfidenceEngine**: validação de qualidade/confiabilidade dos sinais antes de qualquer aprendizado.

O que mudou em relação à v2:
- preferências explícitas deixam de ser implícitas e viram contrato arquitetural hard-constraint;
- aprendizado passa a ter gate de confiança obrigatório (sinal fraco/conflitante não gera patch);
- hierarquia de decisão formalizada com ordem de autoridade;
- integração com memória/RAG separada por tipo de memória (factual, comportamento, preferência).

Por que melhora o sistema:
- reduz risco de aprendizado incorreto e drift;
- aumenta alinhamento com intenção explícita do usuário;
- melhora auditabilidade e explicabilidade de mudanças.

Trade-offs:
- maior complexidade de dados e governança;
- maior latência no ciclo de aprendizado (validação extra);
- menor agressividade adaptativa no início (intencional para segurança).

---

## 1) O que foi adicionado na v3

### 1.1 UserPreferenceLayer (novo)
Camada explícita, versionada e auditável para preferências declaradas pelo usuário.

Funções:
- armazenar preferências explícitas com escopo (`global`, `event_type`, `context`);
- atuar como **override** sobre qualquer política adaptativa;
- impor limites inegociáveis (hard constraints).

Exemplos:
- “não me envie push”;
- “não interrompa conversa ativa”;
- “sempre avise 15 min antes”;
- “evite mensagens longas”;
- “não notifique em horário X”.

### 1.2 SignalConfidenceEngine (novo)
Motor de confiança para validar sinais de aprendizado antes de gerar patch.

Funções:
- classificar tipo de sinal (`explicit`, `implicit`, `behavioral`, `contextual`);
- calcular confiabilidade por consistência/recência/conflito;
- bloquear promoção de sinais fracos, ambíguos ou contraditórios.

---

## 2) Arquitetura Atualizada (v3)

Topologia revisada:

`CalendarEvent -> UserPreferenceLayer -> GuardrailEngine -> AlertPolicyEngine -> NotificationOrchestrator -> DeliveryRouter -> NotificationDispatcher -> FeedbackCollector -> LearningSignalStore -> SignalConfidenceEngine -> Memory/RAG (typed) -> AdaptivePolicyObserver -> PolicyPatchPipeline -> PolicyStore`

Pontos centrais:
- **caminho crítico** permanece determinístico até delivery;
- adaptação continua supervisionada, mas agora só após validação de confiança;
- preferências explícitas entram antes da política adaptativa.

---

## 3) Hierarquia de Decisão (ordem formal de autoridade)

1. **UserPreferenceLayer (hard constraints)**
2. **Guardrails globais** (quiet hours, rate limit, anti-spam, segurança)
3. **AlertPolicyEngine determinístico** (baseline WHEN/WHERE/HOW)
4. **AdaptivePolicy (somente patches válidos e aprovados)**
5. **Delivery** (roteamento/dispatch técnico)

Regra: qualquer conflito entre camada adaptativa e preferência explícita => preferência explícita vence.

---

## 4) UserPreferenceLayer (detalhamento)

## 4.1 Modelo de dados de preferência
Campos recomendados:
- `preference_id`
- `user_id`
- `scope`: `global | event_type | context`
- `dimension`: `timing | channel | style | interruptibility`
- `rule`
- `priority`: `hard | soft`
- `source`: `explicit_user_command | approved_patch | admin`
- `effective_from`, `expires_at`
- `version`, `created_at`, `updated_at`
- `audit_ref`

## 4.2 Interação com WHEN / WHERE / HOW / interruptibility
- **WHEN**: pode fixar offset mínimo/máximo ou exato (`always_15m_before`).
- **WHERE**: pode bloquear canal (`no_push`) ou forçar preferência.
- **HOW**: pode limitar estilo (`short_only`, `avoid_long_messages`).
- **interruptibility**: pode impedir outreach durante conversa ativa.

## 4.3 Regras de precedência
- `hard preference` sempre bloqueia política adaptativa conflitante.
- `soft preference` orienta scoring, mas não quebra guardrail.
- preferências por contexto vencem preferências globais em contexto correspondente.

---

## 5) Learning Signal Confidence Model

## 5.1 Tipos de sinal
- `explicit`: comando claro do usuário (“não envie push”).
- `implicit`: ausência de ação (ignorou alerta).
- `behavioral`: padrão de resposta/engajamento.
- `contextual`: presença, horário, estado da sessão, carga conversacional.

## 5.2 Fatores de confiança
- consistência temporal;
- repetição do padrão em cenários similares;
- similaridade de contexto (mesmo tipo de evento/canal/faixa horária);
- recência com decaimento;
- conflito entre sinais;
- priorização por tipo (`explicit > behavioral > contextual > implicit`).

## 5.3 Estrutura mínima por sinal
Cada sinal deve carregar:
- `signal_id`
- `signal_type`
- `confidence_score` (0..1)
- `weight`
- `decay`
- `reliability_flag` (`high|medium|low|conflicted`)
- `context_fingerprint`
- `evidence_refs`

## 5.4 Regras de promoção
- sinal com `confidence_score` abaixo do threshold não influencia patch;
- sinal `conflicted` só entra via revisão humana ou evidência adicional;
- sinais explícitos podem gerar atualização direta na UserPreferenceLayer (com confirmação conforme risco).

---

## 6) Pipeline de Aprendizado Revisado

Pipeline obrigatório:

`FeedbackCollector -> LearningSignalStore -> SignalConfidenceEngine -> Memory/RAG (typed) -> AdaptivePolicyObserver -> PolicyPatchPipeline -> PolicyStore`

Regras mandatórias:
- nenhum patch sem validação de confiança;
- sinal fraco não altera política;
- sinais conflitantes disparam “state=needs_review”;
- preferências explícitas sempre prevalecem na aplicação final.

### 6.1 Estados de maturidade do patch
- `draft` (evidência insuficiente)
- `candidate` (confiança mínima atingida)
- `canary` (aplicação controlada)
- `promoted` (produção)
- `rolled_back`

---

## 7) Integração com Memória/RAG (refinada)

Separação obrigatória de memória:

1. **Memória factual** (`event_facts`)
- fatos de eventos e entregas (o que aconteceu).

2. **Memória comportamental** (`notification_behavior_signals`)
- sinais observados e agregações por contexto.

3. **Memória de preferência** (`user_notification_preferences`)
- preferências explícitas/inferidas com fonte e confiança.

Regras de uso:
- decisões em tempo real consultam primeiro preferências explícitas;
- memória inferida só influencia via patches aprovados;
- entradas antigas têm decaimento e podem expirar;
- cada decisão referencia `policy_version` + `preference_version`.

Proteções anti-poluição:
- dedupe semântico de sinais repetidos;
- quarantina para sinais de baixa confiança;
- trilha de proveniência (`source`, `evidence_refs`, `trace_id`).

---

## 8) Prevenção de Aprendizado Incorreto

Mecanismos concretos:
- mínimo de evidência por dimensão antes de patch;
- normalização por contexto para evitar inferência por ausência;
- canary rollout por usuário/domínio/event_type;
- comparação before/after com KPI mínimo;
- rollback automático por degradação;
- limite de frequência de mudança (anti-oscillation);
- cooldown após patch para observação limpa.

Anti-overfitting:
- não promover patch com amostra pequena;
- exigir diversidade de contexto;
- penalizar sinais concentrados em uma única janela temporal.

---

## 9) Governança e Auditabilidade (ampliada)

Cada decisão/patch deve registrar:
- sinais usados;
- confiança dos sinais;
- conflito detectado e resolução;
- preferência explícita aplicada (se houver);
- decisão final WHEN/WHERE/HOW + interruptibility;
- versão das políticas/preferências;
- resultado observado pós-entrega.

Capacidades operacionais:
- explicar “por que mudou?” por usuário e por evento;
- rollback por usuário/domínio;
- reset de aprendizado por domínio (`calendar`) sem apagar preferências explícitas;
- export auditável para compliance/debug.

---

## 10) Impacto nos Componentes Existentes

### AlertPolicyEngine
- passa a consumir `ResolvedPreferenceView` antes de gerar plano;
- aplica hard constraints antes de adaptar.

### AdaptivePolicyObserver
- deixa de propor patch direto a partir de sinais brutos;
- passa a consumir apenas sinais validados pelo SignalConfidenceEngine.

### PolicyStore
- versionamento separado: `policy_version` e `preference_version`;
- histórico de aplicação com origem (`adaptive`, `explicit_user`, `admin`).

### PolicyPatchPipeline
- gate adicional obrigatório de confiança + conflito;
- fluxos `canary/promote/rollback` nativos.

### FeedbackCollector
- captura sinais com contexto mais rico (canal, estilo, interruptibility, presença).

### LearningSignalStore
- armazena eventos de sinal crus + agregados;
- suporta decaimento e reconciliação de conflito.

### Novos componentes
- **UserPreferenceStore**: persistência/versionamento de preferências explícitas.
- **SignalConfidenceEngine**: scoring, conflito e elegibilidade de aprendizado.

---

## 11) Efeito da v3 em WHEN / WHERE / HOW

### WHEN
- offset adaptativo só muda com evidência confiável;
- preferência explícita de horário/antecedência pode travar ou limitar adaptação.

### WHERE
- escolha de canal respeita bloqueios explícitos (`no_push`) antes do roteamento;
- adaptação de canal depende de desempenho confiável por contexto.

### HOW
- estilo segue preferência explícita de tom/comprimento;
- mudanças de estilo por aprendizado exigem estabilidade de sinal.

### interruptibility
- deixa de ser apenas variável de otimização e passa a ser também objeto de preferência explícita;
- escalonamento de interrupção exige confiança alta + sem conflito com hard constraints.

---

## 12) Riscos e Limitações

- maior custo de implementação e observabilidade;
- risco de “adaptação lenta” no início por thresholds conservadores;
- necessidade de qualidade de telemetria para não enviesar confiança;
- gestão de conflito explícito vs histórico pode exigir UX de confirmação frequente.

Mitigação:
- rollout progressivo;
- thresholds calibráveis por domínio;
- dashboards de confiança e drift;
- defaults conservadores com fallback determinístico.

---

## 13) Recomendação Final

Adotar v3 como evolução oficial da v2 com foco em três garantias:
1. **Preference-first** (respeito absoluto à intenção explícita).
2. **Confidence-gated learning** (aprendizado só com evidência confiável).
3. **Governança completa** (auditoria, explicação, reversão).

Esse desenho preserva o DNA agentic do Atlas (aprende WHEN/WHERE/HOW), mas com controle forte para evitar comportamento opaco, invasivo ou errático.
