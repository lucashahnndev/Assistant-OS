# Especificação: Acesso Remoto Descentralizado (Capabilities por Provedor)

## 1. Visão Geral
Em vez de uma Capability monolítica (`remote_access`), o sistema adotará uma arquitetura **100% descentralizada**, onde cada provedor de túnel é uma Capability (Plugin) independente. 

Isso garante extrema modularidade: o usuário instala apenas o provedor que deseja usar, e o Agente de IA interage de forma isolada com cada infraestrutura, podendo ter múltiplos túneis ativos simultaneamente.

## 2. Estrutura das Capabilities Individuais

Serão desenvolvidas as seguintes capabilities na pasta `src/capabilities/`:

### A. `ngrok_tunnel`
- **Ferramentas:** `start_ngrok_tunnel()`, `stop_ngrok_tunnel()`, `get_ngrok_status()`
- **Lógica:** Gerencia a thread do `pyngrok`. Requer configuração do Token (AuthToken) no Hub de Capabilities via Vault.

### B. `cloudflare_tunnel`
- **Ferramentas:** `start_cloudflare_tunnel()`, `stop_cloudflare_tunnel()`, `get_cloudflare_status()`
- **Lógica:** Gerencia a thread do `pycloudflared`. Operação "Plug & Play" (trycloudflare) ou uso de token para domínios próprios.

### C. `tailscale_tunnel`
- **Ferramentas:** `get_tailscale_status()`
- **Lógica:** Como o Tailscale é uma VPN a nível de sistema operacional (Kernel), esta capability atua de forma passiva, monitorando o serviço local do Tailscale, capturando logs e extraindo o IP da malha virtual (`100.x.x.x`) para o Agente e para a UI.

## 3. Integração Frontend (UI Dinâmica e Multi-Túnel)

### 3.1. Indicador Unificado no Header (Topbar)
Será adicionado um ícone de **Nuvem (Cloud)** no canto superior direito do painel.
- **Detecção Híbrida:** O frontend detectará ativamente quais destas capabilities estão instaladas e rodando. Se pelo menos uma estiver online, o ícone da Nuvem acende.
- **Popover Multi-Túnel:** Ao clicar na nuvem, o Popover suportará a listagem de múltiplos túneis ativos. Exemplo: se o Ngrok e o Cloudflare estiverem ligados, ele mostrará dois cartões (cards) empilhados, cada um com sua respectiva URL, Status e um mini QR Code individual.

### 3.2. Painel Reativo em Settings (Aba Network)
- A aba "Network" no `Settings.jsx` funcionará como um **Monitor de Acesso Remoto**.
- Ele listará as capabilities de túnel instaladas no sistema.
- Exibirá o status de leitura (read-only) de cada uma delas.
- Fornecerá um botão central do tipo *"Gerenciar no Hub de Capabilities"* que leva o usuário direto para a configuração do respectivo plugin, mantendo o Settings enxuto.

## 4. Vantagens desta Abordagem
- **Concorrência:** O usuário (ou agente) pode subir o Ngrok para um teste rápido e manter o Cloudflare para uso persistente, sem conflitos.
- **Isolamento de Falhas:** Se a API do Ngrok cair, o Cloudflare e a capability dele não serão afetados.
- **Escalabilidade:** Se no futuro houver integração com `LocalTunnel` ou `Pinggy`, basta adicionar um novo plugin sem mexer em código legado.
