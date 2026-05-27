# market-learning-engine.concept.md
# Radar do Caos — Market Learning Engine

## 1. Visão geral

O **Market Learning Engine** é o motor de aprendizado contínuo do Radar do Caos.

A ideia central é transformar o sistema em uma inteligência financeira que não apenas lê notícias, calcula indicadores ou gera previsões isoladas, mas que **aprende continuamente com o próprio histórico de hipóteses, previsões, erros e acertos**.

O objetivo não é criar uma IA que “adivinha o mercado”.  
O objetivo é criar uma máquina de hipóteses testáveis:

```txt
notícia/evento → hipótese → previsão → resultado real → erro/acerto → pós-mortem → aprendizado
```

Com o tempo, o sistema deve se tornar melhor em entender:

- quais notícias realmente movem o mercado;
- quais eventos afetam quais setores;
- quais ativos reagem mais a certos fatores;
- quais modelos funcionam melhor por ativo, setor ou regime de mercado;
- quando a previsão estatística deve ter mais peso;
- quando o contexto noticioso, macroeconômico ou técnico deve reduzir a confiança;
- por que uma previsão deu certo ou errado.

---

## 2. Princípio fundamental

A IA não deve prever preço sozinha.

O LLM deve atuar como:

- intérprete de notícias;
- extrator de eventos;
- analista contextual;
- explicador do raciocínio;
- assistente de pós-mortem;
- interface conversacional com o usuário.

A previsão numérica deve vir de modelos quantitativos, estatísticos ou híbridos.

O Prophet pode ser usado como **baseline estatístico inicial**, mas não deve ser tratado como cérebro final da previsão.

A arquitetura ideal deve combinar:

```txt
modelo estatístico + indicadores técnicos + notícias + macro + fundamentos + histórico de acertos + LLM explicador
```

---

## 3. Objetivo do motor

O Market Learning Engine deve permitir que o Radar do Caos evolua de:

```txt
dashboard financeiro com IA
```

para:

```txt
sistema de inteligência financeira que aprende com o mercado
```

Ele deve ser capaz de:

1. Ler notícias diariamente.
2. Transformar notícias em eventos estruturados.
3. Relacionar eventos com ativos, setores e fatores macro.
4. Gerar hipóteses de impacto.
5. Criar previsões com cenários.
6. Registrar o motivo de cada previsão.
7. Medir o resultado real após o horizonte definido.
8. Calcular erro, acerto e direção.
9. Fazer pós-mortem explicativo.
10. Ajustar pesos por ativo, setor, evento e regime de mercado.
11. Usar memória histórica/RAG para comparar casos parecidos.
12. Melhorar gradualmente suas sugestões e previsões.

---

## 4. Ciclo diário da IA

O ciclo diário do Market Learning Engine deve seguir uma rotina parecida com esta:

```txt
1. Coletar notícias do dia.
2. Coletar preços, volume e indicadores dos ativos.
3. Coletar dados macro relevantes.
4. Extrair eventos das notícias.
5. Classificar impacto por setor/ativo.
6. Consultar memória histórica de eventos parecidos.
7. Gerar hipóteses de mercado.
8. Gerar ou atualizar previsões.
9. Registrar cada previsão com justificativa.
10. Resolver previsões vencidas.
11. Comparar previsão com resultado real.
12. Gerar pós-mortem.
13. Ajustar pesos e confiança.
14. Salvar aprendizados.
15. Produzir alertas, sugestões e resumos para o usuário.
```

---

## 5. Banco de eventos

Notícias não devem ser salvas apenas como texto bruto.

O sistema deve transformar cada notícia relevante em um **evento estruturado**.

Exemplo:

```json
{
  "event_id": "evt_2026_05_23_001",
  "source_news_id": "news_123",
  "event_type": "greve",
  "topic": "caminhoneiros",
  "summary": "Caminhoneiros anunciam greve nacional com potencial impacto em logística e combustíveis.",
  "affected_sectors": ["logística", "combustíveis", "varejo", "alimentos"],
  "affected_assets": ["PETR4", "VBBR3", "RAIZ4", "ASAI3", "CRFB3"],
  "macro_factors": ["diesel", "inflação", "frete", "estoques"],
  "expected_horizon": "curto prazo",
  "expected_impact": {
    "PETR4": "volatilidade/possível positivo",
    "VBBR3": "volatilidade",
    "varejo": "negativo",
    "alimentos": "negativo"
  },
  "confidence": 0.62,
  "reasoning": "Greves podem pressionar frete, abastecimento, estoques e preços de combustíveis."
}
```

Esse formato permite consultas futuras como:

```txt
Quando eventos de greve/logística aconteceram antes, quais ativos reagiram mais?
```

---

## 6. Registro de previsões

Toda previsão deve virar um registro formal.

Nada deve ser “só exibido no gráfico”.

Exemplo:

```json
{
  "prediction_id": "pred_ABEV3_2026_05_23_30d",
  "ticker": "ABEV3",
  "created_at": "2026-05-23",
  "horizon": "30d",
  "current_price": 16.10,
  "scenario_optimistic": 16.80,
  "scenario_base": 16.25,
  "scenario_cautious": 15.55,
  "expected_delta_percent": 0.93,
  "confidence": 0.54,
  "confidence_label": "média-baixa",
  "drivers": [
    "tendência estatística lateral",
    "notícias recentes neutras",
    "volume sem confirmação forte",
    "setor defensivo"
  ],
  "invalidation_factors": [
    "notícia negativa sobre consumo",
    "rompimento de suporte técnico",
    "alta forte de juros futuros"
  ],
  "model_inputs": {
    "statistical_signal": "lateral_positive",
    "technical_signal": "weak",
    "news_signal": "neutral",
    "macro_signal": "neutral_negative",
    "fundamental_signal": "stable"
  },
  "status": "pending"
}
```

Depois do prazo, a previsão deve ser resolvida:

```json
{
  "prediction_id": "pred_ABEV3_2026_05_23_30d",
  "resolved_at": "2026-06-22",
  "actual_price": 15.90,
  "error_percent": -2.15,
  "hit_direction": false,
  "within_predicted_range": true,
  "status": "resolved"
}
```

---

## 7. Avaliação posterior

A avaliação não deve medir apenas se acertou ou errou.

Ela deve responder:

```txt
Por que a previsão deu certo ou errado?
```

Métricas mínimas:

- erro percentual;
- erro absoluto;
- acerto de direção;
- se o preço ficou dentro da faixa prevista;
- acurácia por ticker;
- acurácia por setor;
- acurácia por horizonte;
- acurácia por tipo de evento;
- acurácia por regime de mercado;
- erro médio do modelo;
- comparação com benchmark simples.

Exemplo de pós-avaliação:

```txt
Previsão original:
ABEV3 lateral positiva em 30 dias.

Resultado:
ABEV3 caiu 4,2%.

Causa provável:
O sistema subestimou a pressão de juros futuros e superestimou a estabilidade do setor defensivo.
A leitura técnica já mostrava volume fraco, mas recebeu peso baixo.

Aprendizado:
Aumentar peso de juros futuros para empresas de consumo.
Reduzir confiança quando volume não confirma a tendência estatística.
```

---

## 8. Pós-mortem explicativo

O LLM deve ser usado fortemente no pós-mortem.

Ele deve comparar:

- previsão original;
- drivers usados;
- notícias que surgiram depois;
- variação real do preço;
- mudança de cenário macro;
- indicadores técnicos;
- eventos inesperados.

O pós-mortem deve gerar uma explicação estruturada:

```txt
O que o sistema esperava?
O que aconteceu de verdade?
Qual fator foi subestimado?
Qual fator foi superestimado?
O erro veio de notícia, técnico, macro, fundamentos ou modelo estatístico?
O aprendizado deve alterar quais pesos?
```

Exemplo:

```json
{
  "post_mortem": {
    "main_error_source": "macro",
    "underestimated_factors": ["juros futuros", "aversão a risco"],
    "overestimated_factors": ["tendência estatística", "resiliência do setor"],
    "recommended_weight_changes": {
      "macro_weight": "+0.08",
      "technical_confirmation_weight": "+0.05",
      "statistical_baseline_weight": "-0.06"
    },
    "summary": "A previsão falhou porque o modelo deu peso excessivo à tendência histórica e pouco peso à deterioração macro."
  }
}
```

---

## 9. Ajuste de pesos

O sistema deve começar com pesos simples e explícitos.

Exemplo inicial:

```txt
Modelo estatístico: 40%
Indicadores técnicos: 25%
Notícias/eventos: 20%
Macro: 10%
Fundamentos: 5%
```

Com o tempo, os pesos devem ser ajustados por contexto.

Pesos por ativo:

```txt
PETR4:
- petróleo, política, dividendos e câmbio devem pesar mais.

VALE3:
- minério de ferro, China, dólar e commodities devem pesar mais.

B3SA3:
- juros, volume financeiro, mercado de capitais e regulação devem pesar mais.

FIIs:
- juros, inflação, vacância, dividendos e crédito devem pesar mais.

Bancos:
- Selic, inadimplência, crédito, regulação e balanços devem pesar mais.
```

Pesos por tipo de evento:

```txt
evento regulatório → maior peso para bancos, B3, utilities e setores regulados
evento de commodities → maior peso para PETR4, VALE3, PRIO3, RECV3
evento de juros → maior peso para varejo, construção, FIIs e bancos
evento cambial → maior peso para exportadoras/importadoras
```

Pesos por regime de mercado:

```txt
juros altos
juros em queda
inflação alta
bull market
bear market
crise política
aversão global a risco
commodities em alta
dólar forte
liquidez elevada
```

---

## 10. RAG e memória histórica

O sistema precisa de memória histórica.

Essa memória não deve ser apenas textual.  
Ela deve ser híbrida.

### 10.1 Banco relacional

Para armazenar:

- previsões;
- resultados;
- erros;
- acertos;
- pesos;
- eventos estruturados;
- ativos impactados;
- métricas de modelo;
- histórico de pós-mortem.

### 10.2 Banco vetorial

Para armazenar:

- notícias;
- análises antigas;
- relatórios;
- resumos;
- pós-mortems;
- explicações da IA;
- documentos de mercado;
- eventos semanticamente parecidos.

### 10.3 Séries temporais

Para armazenar:

- preços;
- volume;
- volatilidade;
- indicadores técnicos;
- macro;
- commodities;
- juros;
- câmbio.

### 10.4 Knowledge graph

Opcional, mas poderoso.

Pode mapear:

```txt
evento → setor → ativo → impacto esperado → resultado real → aprendizado
```

Exemplo:

```txt
Greve → logística → varejo → impacto negativo → queda média observada → peso ajustado
```

---

## 11. Consulta a casos parecidos

Antes de gerar uma nova previsão, o sistema deve perguntar à memória:

```txt
Já aconteceu algo parecido?
Quais ativos reagiram?
Qual foi a direção?
Qual foi a magnitude?
O sistema acertou ou errou na época?
Quais fatores explicaram o movimento?
```

Exemplo de consulta:

```txt
Evento atual:
Alta forte do petróleo + notícia política envolvendo Petrobras.

Buscar:
eventos parecidos com petróleo + Petrobras + risco político nos últimos anos.

Retornar:
- casos similares;
- reação média;
- dispersão;
- principais exceções;
- confiança histórica.
```

Isso permite que a IA diga:

```txt
Eventos parecidos no passado costumaram gerar alta volatilidade em PETR4, mas a direção dependeu do contexto político e do preço internacional do petróleo.
```

---

## 12. Motor de cenários

O motor de cenários deve gerar:

- cenário otimista;
- cenário base;
- cenário cauteloso;
- faixa provável;
- confiança;
- fatores de sustentação;
- fatores de invalidação.

O Prophet ou outro modelo estatístico pode gerar a linha base.

Depois:

```txt
indicadores técnicos ajustam força e confirmação;
notícias ajustam viés e risco;
macro ajusta confiança;
fundamentos ajustam horizonte maior;
memória histórica ajusta probabilidade;
LLM explica o raciocínio.
```

No início, notícias e eventos não devem alterar agressivamente o preço previsto.  
Eles devem primeiro ajustar:

- confiança;
- viés;
- peso dos cenários;
- alertas;
- invalidações.

Exemplo:

```txt
Prophet prevê R$ 16,20.

Notícia negativa não muda automaticamente para R$ 14,00.
Ela faz o sistema:
- aumentar peso do cenário cauteloso;
- reduzir confiança;
- adicionar fator de risco;
- criar alerta;
- explicar a incerteza.
```

---

## 13. Papel do Prophet

Prophet deve ser usado como baseline inicial.

Ele pode ajudar a gerar:

- tendência estatística;
- faixa prevista;
- sazonalidade;
- ponto inicial dos cenários.

Mas Prophet não entende:

- notícias;
- eventos;
- política;
- fundamentos;
- macroeconomia;
- balanços;
- comportamento setorial;
- choques de mercado.

Portanto:

```txt
Prophet não deve decidir sozinho.
Prophet deve ser uma fonte de sinal.
```

---

## 14. Papel do LLM

O LLM deve atuar como camada semântica e explicativa.

Ele deve:

- ler notícia;
- extrair evento;
- classificar impacto;
- conectar ativos e setores;
- resumir riscos;
- explicar previsões;
- gerar pós-mortem;
- responder perguntas do usuário;
- consultar RAG/memória;
- comparar casos parecidos.

O LLM não deve:

- inventar preço;
- prever sozinho;
- substituir modelo quantitativo;
- gerar recomendação absoluta;
- esconder incerteza.

---

## 15. Modelos futuros

Quando houver dados próprios suficientes, o sistema pode evoluir para:

- XGBoost;
- LightGBM;
- modelos de classificação de direção;
- modelos por setor;
- modelos por ativo;
- ensembles;
- modelos de volatilidade;
- ranking de modelos por ativo;
- meta-modelo de confiança;
- modelos de regime de mercado.

Exemplo futuro:

```txt
Para PETR4, modelo de commodities + notícias políticas teve melhor desempenho.
Para ABEV3, modelo macro + consumo teve melhor desempenho.
Para FIIs, juros e inflação foram mais preditivos que notícias gerais.
```

---

## 16. Carteira sombra da IA

Antes de qualquer automação real, o sistema deve ter uma carteira simulada.

A IA pode criar estratégias fictícias:

```txt
Carteira IA Conservadora
Carteira IA Moderada
Carteira IA Agressiva
```

Cada decisão simulada deve registrar:

- ativo;
- data;
- preço;
- motivo;
- confiança;
- cenário;
- resultado;
- erro/acerto;
- comparação com benchmark.

Métricas:

- retorno;
- volatilidade;
- drawdown;
- taxa de acerto;
- Sharpe;
- comparação com CDI, Ibovespa e S&P 500.

A IA só deve ganhar autoridade se provar desempenho no modo sombra.

---

## 17. Integração com o modal de ativo

O modal de ativo deve ser uma das principais interfaces desse motor.

Ele deve mostrar:

```txt
O que está acontecendo com esse ativo?
Qual é a previsão?
Por que essa previsão existe?
Qual é a confiança?
O que pode invalidar o cenário?
Que notícias impactam o ativo?
O sistema já viu casos parecidos?
Como o modelo se saiu no passado com esse ticker?
```

A aba Previsão deve mostrar:

- valor esperado;
- faixa provável;
- cenários;
- confiança;
- erro histórico;
- por que;
- invalidações;
- limitações;
- gráfico como apoio visual.

A aba IA deve permitir:

- perguntar sobre o ativo;
- perguntar sobre a previsão;
- perguntar sobre notícias;
- perguntar por que o sistema acredita em certo cenário;
- abrir conversa completa no Caos GPT sem perder contexto.

---

## 18. Sugestões da IA

As sugestões devem nascer do Market Learning Engine.

Elas não devem ser frases genéricas.

Cada sugestão deve conter:

```txt
Tipo: risco/oportunidade/alerta/rebalanceamento/previsão
Ativos impactados
Evento relacionado
Cenário esperado
Confiança
Motivos
Invalidações
Ações possíveis
```

Exemplo:

```txt
Tipo: Risco
Ativo: PETR4
Evento: queda do petróleo + notícia política
Cenário: aumento de volatilidade no curto prazo
Confiança: média
Motivos:
- petróleo caiu 2,4%;
- notícia política aumentou incerteza;
- histórico mostra alta sensibilidade nesse regime.
Ação sugerida:
- simular impacto;
- criar alerta;
- não aumentar posição antes de nova confirmação.
```

---

## 19. Roadmap incremental

### Fase 1 — Registro disciplinado

Implementar:

- tabela de eventos estruturados;
- tabela de previsões;
- tabela de resultados;
- armazenamento dos motivos da previsão;
- histórico de preços no momento da previsão.

Sem isso, não existe aprendizado.

### Fase 2 — Previsão explicável

Implementar:

- cenário base;
- otimista;
- cauteloso;
- faixa provável;
- confiança;
- motivos;
- invalidações;
- limitações;
- exibição no modal de ativo.

### Fase 3 — Avaliação automática

Criar job diário para:

- encontrar previsões vencidas;
- comparar com preço real;
- calcular erro;
- calcular acerto de direção;
- marcar previsão como resolvida.

### Fase 4 — Pós-mortem com LLM

Para previsões resolvidas:

- gerar análise do erro;
- identificar fator subestimado;
- identificar fator superestimado;
- sugerir ajustes de peso;
- salvar aprendizado.

### Fase 5 — Ajuste de pesos

Começar com regras simples.

Exemplo:

```txt
Se Prophet erra repetidamente em um ativo, reduzir confiança estatística para esse ticker.
Se notícias explicam melhor movimentos de curto prazo em um setor, aumentar peso de eventos nesse setor.
Se volume confirma melhor rompimentos, aumentar peso técnico.
```

### Fase 6 — RAG histórico

Criar memória vetorial para:

- notícias antigas;
- eventos antigos;
- pós-mortems;
- análises passadas;
- casos parecidos.

### Fase 7 — Modelos adicionais

Adicionar:

- modelos por setor;
- modelos de classificação de direção;
- ensemble;
- ranking de modelos;
- meta-modelo de confiança.

---

## 20. Regras de segurança e honestidade

O sistema nunca deve prometer certeza.

Evitar:

```txt
Compre.
Venda.
Vai subir.
Vai cair.
Lucro garantido.
```

Preferir:

```txt
Cenário provável.
Hipótese.
Sinal.
Risco.
Monitorar.
Simular.
Criar alerta.
Confiança baixa/média/alta.
```

Texto obrigatório para previsões:

```txt
Esta previsão é uma hipótese baseada em dados históricos, sinais atuais e contexto disponível. Não é recomendação financeira.
```

---

## 21. Frase-mãe do sistema

A IA não deve apenas prever.

Ela deve:

```txt
criar hipóteses,
registrar hipóteses,
testar hipóteses,
medir hipóteses,
explicar erros,
ajustar pesos,
e aprender com o próprio histórico.
```

---

## 22. Definição final

O Market Learning Engine é o núcleo que transforma o Radar do Caos em uma inteligência financeira viva.

Ele aprende porque registra o que pensou, mede o que aconteceu e corrige como pensa.

Sem histórico, a IA apenas interpreta.  
Com histórico, ela compara.  
Com comparação, ela aprende.  
Com aprendizado, ela melhora suas previsões e sugestões.

Esse é o diferencial central do Radar do Caos.
