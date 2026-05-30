# market-learning-engine.concept.md
# Radar do Caos - Market Learning Engine

## 1. Visao geral

O **Market Learning Engine** e o motor de aprendizado continuo do Radar do Caos.

A ideia central e transformar o sistema em uma inteligencia financeira que nao apenas le noticias, calcula indicadores ou gera previsoes isoladas, mas que **aprende continuamente com o proprio historico de hipoteses, previsoes, erros e acertos**.

O objetivo nao e criar uma IA que "adivinha o mercado".
O objetivo e criar uma maquina de hipoteses testaveis:

```txt
noticia/evento -> hipotese -> previsao -> resultado real -> erro/acerto -> pos-mortem -> aprendizado
```

Com o tempo, o sistema deve se tornar melhor em entender:

- quais noticias realmente movem o mercado;
- quais eventos afetam quais setores;
- quais ativos reagem mais a certos fatores;
- quais modelos funcionam melhor por ativo, setor ou regime de mercado;
- quando a previsao estatistica deve ter mais peso;
- quando o contexto noticioso, macroeconomico ou tecnico deve reduzir a confianca;
- por que uma previsao deu certo ou errado.

---

## 2. Principio fundamental

A IA nao deve prever preco sozinha.

O LLM deve atuar como:

- interprete de noticias;
- extrator de eventos;
- analista contextual;
- explicador do raciocinio;
- assistente de pos-mortem;
- interface conversacional com o usuario.

A previsao numerica deve vir de modelos quantitativos, estatisticos ou hibridos.

O Prophet pode ser usado como **baseline estatistico inicial**, mas nao deve ser tratado como cerebro final da previsao.

A arquitetura ideal deve combinar:

```txt
modelo estatistico + indicadores tecnicos + noticias + macro + fundamentos + historico de acertos + LLM explicador
```

---

## 3. Objetivo do motor

O Market Learning Engine deve permitir que o Radar do Caos evolua de:

```txt
dashboard financeiro com IA
```

para:

```txt
sistema de inteligencia financeira que aprende com o mercado
```

Ele deve ser capaz de:

1. Ler noticias diariamente.
2. Transformar noticias em eventos estruturados.
3. Relacionar eventos com ativos, setores e fatores macro.
4. Gerar hipoteses de impacto.
5. Criar previsoes com cenario.
6. Registrar o motivo de cada previsao.
7. Medir o resultado real apos o horizonte definido.
8. Calcular erro, acerto e direcao.
9. Fazer pos-mortem explicativo.
10. Ajustar pesos por ativo, setor, evento e regime de mercado.
11. Usar memoria historica/RAG para comparar casos parecidos.
12. Melhorar gradualmente suas sugestoes e previsoes.

---

## 4. Ciclo diario da IA

O ciclo diario do Market Learning Engine deve seguir uma rotina parecida com esta:

```txt
1. Coletar noticias do dia.
2. Coletar precos, volume e indicadores dos ativos.
3. Coletar dados macro relevantes.
4. Extrair eventos das noticias.
5. Classificar impacto por setor/ativo.
6. Consultar memoria historica de eventos parecidos.
7. Gerar hipoteses de mercado.
8. Gerar ou atualizar previsoes.
9. Registrar cada previsao com justificativa.
10. Resolver previsoes vencidas.
11. Comparar previsao com resultado real.
12. Gerar pos-mortem.
13. Ajustar pesos e confianca.
14. Salvar aprendizados.
15. Produzir alertas, sugestoes e resumos para o usuario.
```

---

## 5. Banco de eventos

Noticias nao devem ser salvas apenas como texto bruto.

O sistema deve transformar cada noticia relevante em um **evento estruturado**.

Exemplo:

```json
{
  "event_id": "evt_2026_05_23_001",
  "source_news_id": "news_123",
  "event_type": "greve",
  "topic": "caminhoneiros",
  "summary": "Caminhoneiros anunciam greve nacional com potencial impacto em logistica e combustiveis.",
  "affected_sectors": ["logistica", "combustiveis", "varejo", "alimentos"],
  "affected_assets": ["PETR4", "VBBR3", "RAIZ4", "ASAI3", "CRFB3"],
  "macro_factors": ["diesel", "inflacao", "frete", "estoques"],
  "expected_horizon": "curto prazo",
  "expected_impact": {
    "PETR4": "volatilidade/possivel positivo",
    "VBBR3": "volatilidade",
    "varejo": "negativo",
    "alimentos": "negativo"
  },
  "confidence": 0.62,
  "reasoning": "Greves podem pressionar frete, abastecimento, estoques e precos de combustiveis."
}
```

Esse formato permite consultas futuras como:

```txt
Quando eventos de greve/logistica aconteceram antes, quais ativos reagiram mais?
```

---

## 6. Registro de previsoes

Toda previsao deve virar um registro formal.

Nada deve ser "so exibido no grafico".

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
  "confidence_label": "media-baixa",
  "drivers": [
    "tendencia estatistica lateral",
    "noticias recentes neutras",
    "volume sem confirmacao forte",
    "setor defensivo"
  ],
  "invalidation_factors": [
    "noticia negativa sobre consumo",
    "rompimento de suporte tecnico",
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

Depois do prazo, a previsao deve ser resolvida:

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

## 7. Avaliacao posterior

A avaliacao nao deve medir apenas se acertou ou errou.

Ela deve responder:

```txt
Por que a previsao deu certo ou errado?
```

Metricas minimas:

- erro percentual;
- erro absoluto;
- acerto de direcao;
