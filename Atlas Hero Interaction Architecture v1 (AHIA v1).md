# Atlas Hero Interaction Architecture v1 (AHIA v1)

Documento interno que define a arquitetura de UI do Atlas para a tela
inicial (Dashboard/Command Center), com foco em **interação**,
**observabilidade**, **modo voz**, **execução ao vivo**, e **mídias
dinâmicas**, sem regressão do Console atual.

------------------------------------------------------------------------

## 0) Objetivos

-   Transformar a tela inicial em um **Command Center**: interação +
    estado do runtime.
-   Manter o **Console** como workspace detalhado (chat completo,
    configs, debug).
-   Entregar uma UI **robusta**, **sóbria**, **densa o suficiente**, mas
    com **foco no que importa**: interação.
-   Suportar um **Hero Interativo** com estados: Texto / Voz / Execução
    / Mídia.
-   Garantir **não regressão** de funcionalidades existentes.
-   Preparar a base para futuras ações globais.

------------------------------------------------------------------------

## 1) Taxonomia de Camadas

### 1.1 SYSTEM GLOBAL

1.  Global Header (colapsável)
2.  Left Nav Bar (colapsado por padrão)

### 1.2 HERO

3.  Hero Menu (Observability Stack, colapsável com scroll)
4.  Hero Interactive Surface (estado-driven)
5.  Media Column (pilha dinâmica com expiração)

------------------------------------------------------------------------

## 2) Layout Base (Desktop)

### Estrutura

\[SYSTEM HEADER\] \[NAV\] \[HERO MENU\] \[INTERACTIVE SURFACE\] \[MEDIA
COLUMN\]

### Proporções sugeridas

-   Hero Menu expandido: 280--360px
-   Media Column: 300--360px
-   Centro: área dominante

------------------------------------------------------------------------

## 3) Hero Interactive Surface

Sub-áreas: - Orb / Surface Slot - User Input - Thought / Response
Stream - Mode Controls

------------------------------------------------------------------------

## 4) State Machine

Estados principais:

-   TEXT_IDLE
-   TEXT_ACTIVE
-   VOICE_LISTENING
-   VOICE_THINKING
-   VOICE_SPEAKING
-   LIVE_EXECUTION
-   MEDIA_FOCUS
-   IMMERSIVE

Prioridade de Surface: LIVE_EXECUTION \> MEDIA_FOCUS \> VOICE \> TEXT

------------------------------------------------------------------------

## 5) Fluxos

### Texto

Timeline minimalista (sem balões). Prefixos discretos: User / Atlas.

### Voz

Orb ativo durante escuta. Status resumido durante pensamento. Resposta
aparece em tempo real.

### Execução ao vivo

Playback substitui orb. Timeline continua abaixo.

### Mídia

Foco central temporário (6--10s). Depois dock na coluna direita. Expira
após timeout.

------------------------------------------------------------------------

## 6) Media Stack

Tipos: - YouTube - Link preview - Imagem - Vídeo - Documento - Playback
mini

Regras: - Apenas 1 foco por vez. - Novo item substitui foco anterior. -
Hover pausa expiração.

------------------------------------------------------------------------

## 7) Observabilidade

Snapshot compacto: - Tokens - Latência - Modelo ativo - Workers ativos -
Sessions ativas

Detalhes apenas expandindo.

------------------------------------------------------------------------

## 8) Tokens UI

Radius: - 5px inputs - 8px botões - 12px cards - 16px containers

Menos azul saturado. Dark levemente mais escuro. Densidade \~10--15%
maior.

------------------------------------------------------------------------

## 9) Não Regressão

Não quebrar: - Console - Sessões - Sidebar - Playback - Skills -
Memory - Security - Settings

------------------------------------------------------------------------

## 10) Definition of Done

-   Dashboard utilizável como ponto principal de interação.
-   Alternância correta entre Orb, Playback e Media.
-   Timeline sem estilo de chat social.
-   Media dock funcional e com expiração.
-   Responsivo.
