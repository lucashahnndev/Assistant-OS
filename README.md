# Assistant-OS

<p align="center">
  <img src="images/logo.png" alt="Assistant-OS logo" width="180">
</p>

<p align="center">
  <strong>An operator-grade runtime for Atlas.</strong><br>
  Capability-based action orchestration, guarded execution, and session memory that keeps the system honest.
</p>

<p align="center">
  <a href="#what-it-is">What it is</a> ·
  <a href="#why-it-exists">Why it exists</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#getting-started">Getting started</a> ·
  <a href="#for-agents">For agents</a>
</p>

<p align="center">
  <img src="images/bg/elegant-wave.webp" alt="Assistant-OS visual banner" width="100%">
</p>

## What it is

Assistant-OS is a modular runtime platform built to let Atlas operate with structure, memory, and guardrails.

It is designed to:

- orchestrate actions through capabilities instead of hard-coded monoliths;
- enforce granular access control by user or group;
- support multiple drivers such as web, Telegram, CLI, and voice;
- keep operational memory, snapshots, and live sessions coherent;
- separate semantic intent from execution so the runtime can validate, gate, and record.

The runtime is not the semantic agent.
Atlas holds semantic authority. Assistant-OS provides the track, contract, brake, and black box.

## Why it exists

Most assistant stacks fail in the same places: they blur intent and execution, they lose state across channels, and they make debugging feel like archaeology.

Assistant-OS exists to solve that problem with a cleaner operating model:

- predictable session contracts;
- canonical event pipelines;
- snapshot + WebSocket reconciliation;
- voice and transcript support under the same session model;
- durable indexes for thoughts, messages, feedback, playback, and audit trails.

## What makes it different

<table>
  <tr>
    <td><strong>Capability-first</strong><br>Each action lives behind a contract, not just a prompt.</td>
    <td><strong>Session-native</strong><br>Messages, thoughts, streams, and feedback share a canonical timeline.</td>
  </tr>
  <tr>
    <td><strong>Multi-channel</strong><br>Web, voice, Telegram, and CLI can converge on the same runtime.</td>
    <td><strong>Guardrailed</strong><br>The runtime validates, gates, records, and executes before anything becomes user-visible truth.</td>
  </tr>
</table>

## Architecture

```text
src/
  core/        orchestration, session, ACL, intent resolution
  server/      FastAPI API and routes
  drivers/     channel and interface integrations
  services/    LLM, memory, workspace, and safety services
  capabilities/  action plugins with contract + runtime
frontend/      React web panel
data/          configuration, sessions, identities, artifacts
tests/         automated contract and behavior checks
scripts/       operational utilities
```

At a high level:

1. Atlas decides meaning and intent.
2. Assistant-OS resolves, validates, and routes the action.
3. Capabilities execute under policy and access control.
4. Sessions persist the canonical record for replay, audit, and recovery.

## Core capabilities

- action orchestration
- memory management
- browser control
- calendar and notifications
- system control and system apps
- vision and assistive overlay
- logs, search, and retrieval
- voice-aware session handling
- feedback and reasoning timelines

## Product surfaces

- `frontend/` for the React-based web panel
- `src/server/` for the API and session routes
- `src/capabilities/` for modular runtime actions
- `docs/` for human-readable continuity, guides, and reports

## Getting started

### 1. Create a virtual environment

```bash
python -m venv env
```

### 2. Install dependencies

```bash
./env/bin/pip install -r requirements.txt
```

### 3. Configure the runtime

- main file: `data/config.json`
- example baseline: `config.json.example`

### 4. Run the backend API

```bash
PYTHONPATH=src ./env/bin/python -m uvicorn src.server.main:create_app --factory --host 0.0.0.0 --port 8000
```

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

### 6. Run tests

```bash
PYTHONPATH=src ./env/bin/python -m pytest -q tests
```

## In practice

This repository currently emphasizes:

- canonical session snapshots;
- live event reconciliation;
- thought and reasoning timelines;
- voice transcript and playback flow;
- feedback persistence;
- capability contracts and test coverage.

That makes the system easier to observe, safer to extend, and much easier to debug when multiple drivers are active at once.

## For agents

If you are an agent working in this repository:

1. Read [`AGENTS.md`](AGENTS.md).
2. Continue with [`project.overview.md`](project.overview.md).
3. Then open [`agent-start-here.md`](agent-start-here.md).

For update workflows, also read:

- [`project.update.md`](project.update.md)
- [`project.migrations.md`](project.migrations.md)

## Scripts

- `scripts/test_bridge.py`: CLI bridge for manual flow testing
- `scripts/validate_agent.py`: guided manual validation suite

## License

BSD 3-Clause. See [`LICENSE`](LICENSE).
