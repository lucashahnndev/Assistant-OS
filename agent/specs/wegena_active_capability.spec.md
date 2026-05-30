# Wegena Active Capability Spec

## Overview

O Wegena evoluiu de um visualizador de partículas embutido passivo para uma **Capability de Primeira Classe**. Agora o agente pode invocar o motor gráfico proativamente para gerar ambientes e cenas visuais em resposta ao usuário. 

Além disso, introduzimos um mecanismo de persistência de mídia e feedback do usuário, estabelecendo a base para um aprendizado contínuo (RAG de estilos).

## Componentes do Contrato

1.  **Capability (`wegena`)**:
    *   Ação: `generate_scene`.
    *   Entrada: Descrição textual da cena.
    *   Saída: Script `.weg` gerado através do LLM, consumindo `budget` e `max_particles` parametrizáveis via `config.json`.
2.  **Artefatos de Mídia (Sessão)**:
    *   Todo script `.weg` gerado (seja de forma ativa pela capability ou passiva pelo Observer) deve ser salvo fisicamente em disco (ex: `/data/workspace/wegena/scene_X.weg`).
    *   Esse arquivo é retornado no array de media para que o `Orchestrator` o insira no histórico de chat e na aba *Media* do inspetor.
3.  **UI Feedback (Nexus & Chat)**:
    *   Cenas são renderizadas no chat através de um componente dedicado (ex: `WegenaAssistCard`).
    *   A UI de controle da cena deve incluir botões discretos de **Feedback (Like/Dislike)** ao lado do botão de limpar cena.
    *   O feedback é persistido (ex: `localStorage` atrelado ao ID da cena/arquivo) para garantir que a UI recarregue o estado do botão corretamente.
4.  **Learning Loop (RAG)**:
    *   Quando `learning_enabled = true` no `config.json`, os feedbacks de *Like* servirão para marcar os scripts `.weg` gerados como "Hits".
    *   No futuro, esses "Hits" serão anexados no prompt do subagente como exemplos *Few-Shot* dinâmicos, ensinando ao modelo os gostos estéticos do usuário.

## Restrições

*   **Custos de Renderização**: Para evitar gargalos no navegador, o histórico de chat não instancia múltiplos WebGLs. Ele exibe um "Card" com o script salvo e um botão que envia o evento para renderizar no motor principal (Orb).
*   **Aparência Premium**: Ícones referentes ao Wegena devem abandonar metáforas abstratas (estrela) e adotar ícones literais de ambiente (Montanha, Paisagem ou Terra).
