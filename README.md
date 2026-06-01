# Assistant-OS

Modular agent platform focused on:
- capability-based action orchestration;
- granular access control per user/group;
- multiple drivers (web, telegram, cli, voice);
- operational memory and loop execution with guardrails.

If you are an agent, start with [`AGENTS.md`](AGENTS.md), then read
[`project.overview.md`](project.overview.md) and
[`agent-start-here.md`](agent-start-here.md).

## For agents

### Install

Read [`AGENTS.md`](AGENTS.md), apply `standard` to this project, and before any
commit show:

- created files;
- `git status --short`;
- doubts or conflicts.

### Update

Read [`AGENTS.md`](AGENTS.md). If `awc.meta.toon` diverges, open
[`project.update.md`](project.update.md) and
[`project.migrations.md`](project.migrations.md), then continue through
[`project.overview.md`](project.overview.md) and
[`agent-start-here.md`](agent-start-here.md). Before any commit show:

- `trace_id`;
- created files;
- changed files;
- `git status --short`;
- doubts or conflicts.

## Current State (v2 base)
- Core architecture in `src/core`, `src/server`, `src/services`, `src/capabilities`.
- React frontend in `frontend/`.
- Knowledge capability stack with:
  - `web.search.discover` (`links|knowledge|auto` mode);
  - `wikipedia.search` (structured output for RAG).

## Structure
```text
src/
  core/        # orchestration, session, ACL, intent resolution
  server/      # FastAPI API and routes
  drivers/     # interface/channel integrations
  services/    # support services (LLM, memory, workspace, safety)
  capabilities/      # action plugins (contract + runtime)
frontend/      # React web panel
data/          # configuration, sessions, identities, artifacts
tests/         # lean automated test suite
scripts/       # operational utilities (bridge/validation)
```

## Quick Setup
1. Create virtual environment:
```bash
python -m venv env
```

2. Install dependencies:
```bash
./env/bin/pip install -r requirements.txt
```

3. Adjust configuration:
- main file: `data/config.json`
- base example: `config.json.example`

## Run
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

## Tests
Run:
```bash
PYTHONPATH=src ./env/bin/python -m pytest -q tests
```

Main coverage:
- intent resolution;
- loop guardrails and action normalization;
- permissions and user scope;
- capability quality/contract;
- orchestrator flow integration.

## Scripts
Maintained scripts:
- `scripts/test_bridge.py`: CLI bridge for manual flow testing.
- `scripts/validate_agent.py`: guided manual validation suite.

## License
BSD 3-Clause. See `LICENSE`.
