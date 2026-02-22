# Assistant-OS (Atlas)

Plataforma de agente modular com foco em:
- orquestração de ações por skills;
- controle de acesso granular por usuário/grupo;
- múltiplos drivers (web, telegram, cli, voz);
- memória operacional e execução em loop com guardrails.

## Estado Atual (v2 base)
- Arquitetura principal em `src/core`, `src/server`, `src/services`, `src/skills`.
- Frontend React em `frontend/`.
- Stack de skills de conhecimento com:
  - `web.search.discover` (modo `links|knowledge|auto`);
  - `wikipedia.search` (retorno estruturado para RAG).

## Estrutura
```text
src/
  core/        # orquestração, sessão, ACL, resolução de intenção
  server/      # API FastAPI e rotas
  drivers/     # integrações de interface/canal
  services/    # serviços de suporte (LLM, memória, workspace, safety)
  skills/      # plugins de ação (contrato + runtime)
frontend/      # painel web React
data/          # configuração, sessões, identidades e artefatos
tests/         # suíte enxuta de testes automatizados
scripts/       # utilitários operacionais (bridge/validação)
```

## Setup Rápido
1. Criar ambiente virtual:
```bash
python -m venv env
```

2. Instalar dependências:
```bash
./env/bin/pip install -r requirements.txt
```

3. Ajustar configuração:
- arquivo principal: `data/config.json`
- exemplo base: `config.json.example`

## Execução
### Backend API
```bash
PYTHONPATH=src ./env/bin/python -m uvicorn src.server.main:create_app --factory --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Testes
A pasta `tests/` foi reduzida para uma suíte objetiva e mantida.

Executar:
```bash
PYTHONPATH=src ./env/bin/python -m pytest -q tests
```

Coberturas principais:
- resolução de intenção;
- guardrails de loop e normalização de ação;
- permissões e escopo por usuário;
- qualidade/contrato das skills;
- integração de fluxo do orquestrador.

## Scripts
Scripts mantidos:
- `scripts/test_bridge.py`: bridge CLI para testes manuais de fluxo.
- `scripts/validate_agent.py`: suíte de validação manual guiada.

## Licença
BSD 3-Clause. Veja `LICENSE`.
