# Guia de Comunicação e Testes do Atlas

Este guia descreve as formas de interagir com o agente Atlas para testar fluxos de resposta, memória, contexto e habilidades.

## 1. Canais de Comunicação Existentes

### 📱 Telegram Driver
Utilize o Telegram para testar a experiência real de chat.
- **Configuração**: Adicione seu `botkey` em `.env` ou `data/config.json`.
- **Uso**: Inicie o kernel (`python src/main.py`) e envie mensagens para o seu bot.

### 🎙️ Voice Driver
Teste as capacidades de voz e interação via áudio.
- **Configuração**: Ative o driver de voz no `data/config.json`.
- **Uso**: Diga a palavra de ativação "Atlas" seguida do comando.

### 💻 Console Client (WebSocket)
Uma forma rápida de testar via terminal usando o protocolo WebSocket.
- **Uso**:
  1. Inicie o kernel: `python src/main.py`
  2. Em outro terminal: `python tests/console_client.py`
- **Vantagem**: Mostra logs técnicos e chunks de resposta em tempo real.

### 🔌 REST API / Webhooks
Interaja programaticamente através do `ServerDriver`.
- **Endpoint**: `POST http://localhost:8000/webhook`
- **Payload**: `{"message": "Olá Atlas"}`

---

## 2. Ponte de Teste Dedicada (`test_bridge.py`)

Para testes avançados e depuração técnica, criamos a ferramenta `scripts/test_bridge.py`.

### Funcionalidades:
- **Chat Direto**: Conversa direta com o `AgentOrchestrator` sem drivers externos.
- **Inspeção de Memória**: Veja o estado atual da sessão e histórico consolidado.
- **Teste de Skills**: Force o disparo de uma habilidade específica.
- **Injeção de Contexto**: Simule estados complexos para testar a coerência do agente.

### Como usar:
```bash
python scripts/test_bridge.py
```

### Comandos Especiais no Console:
- `/memory`: Exibe o conteúdo da memória da sessão atual.
- `/skills`: Lista todas as habilidades carregadas.
- `/context`: Mostra o resumo do estado (TOON) enviado ao LLM.
- `/clear`: Limpa o histórico da sessão atual.

## Relacionados

- [../README.md](../README.md): indice geral da documentacao humana.
- [../architecture/README.md](../architecture/README.md): contexto arquitetural para os testes de runtime.
- [../reports/README.md](../reports/README.md): lugar natural para registrar resultados de teste e diagnósticos.
- [../policies/README.md](../policies/README.md): regras de governanca que guiam validacoes e rollback.
- [../../agent/specs/atlas_operating_model.spec.md](../../agent/specs/atlas_operating_model.spec.md): contrato operacional que afeta prompt, discovery, tool use e approval.
