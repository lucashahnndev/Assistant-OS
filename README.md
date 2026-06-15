# Assistant-OS

<p align="center">
  <img src="images/logo.png" alt="Assistant-OS logo" width="180">
</p>

<p align="center">
  <strong>Atlas is not just something you talk to.</strong><br>
  It is an assistant that can live with your routine, your projects, your machine, and your attention.
</p>

<p align="center">
  <a href="#why-people-want-this">Why people want this</a> ·
  <a href="#what-atlas-actually-does">What Atlas actually does</a> ·
  <a href="#why-it-feels-different">Why it feels different</a> ·
  <a href="#see-the-product">See the product</a> ·
  <a href="#getting-started">Getting started</a>
</p>

<p align="center">
  <img src="images/app-login.png" alt="Atlas login screen" width="100%">
</p>

## Why people want this

Most assistants are impressive for a minute and frustrating by the end of the day.

They answer, but they do not accompany.
They help once, but do not hold context.
They generate text, but do not reduce operational weight.

Atlas is built for a different expectation:

- something that helps you remember, organize, and execute;
- something that can keep up with your projects and your machine;
- something that feels less like a disposable chat and more like a real operational presence;
- something that can reduce friction instead of adding one more interface to manage.

## What Atlas actually does

Atlas is meant to be useful in the ways people actually care about:

- organize your agenda and help keep your day from slipping;
- remind you about what matters before it becomes urgent;
- research information for you instead of making you chase tabs and sources alone;
- perform repetitive browser work and UI-heavy tasks;
- live on your computer and understand the state of the system around it;
- open, inspect, and control local apps and workflows;
- keep track of conversation, context, thoughts, feedback, and ongoing work;
- help you operate locally or remotely with more continuity and less chaos.

In other words, Atlas is not only about answering questions.
It is about turning intention into action inside a real environment.

## Why it feels different

The difference is not just that Atlas can do more.
It is that Atlas is designed to feel more continuous, more grounded, and more trustworthy.

Instead of behaving like a blank chat box every time you return, it is built around:

- persistent sessions;
- visible reasoning and execution trails;
- memory that can be recalled later;
- task and work tracking;
- browser, system, and research capabilities under one roof;
- voice, text, and live session flow sharing the same operational model.

That creates a very different emotional outcome:

- less repetition;
- less context loss;
- less guessing about what happened;
- more clarity;
- more control;
- more confidence using it for real work.

## Built for real-world use

Atlas already covers a wide surface of practical use cases:

- browser automation and UI interaction;
- system control, apps, files, logs, and status;
- long-term and episodic memory;
- notifications and reminders;
- task orchestration and worker tracking;
- calendar and Google Calendar sync;
- weather, maps, and information lookup;
- retrieval across web, Wikipedia, research, YouTube, music, and structured sources;
- screen vision and assistive overlay;
- immersive voice and console-style interaction.

This is what gives Atlas its shape as a product:
not one trick, but a growing operational layer around your digital life.

## See the product

Atlas is presented more like an operating console than a generic chatbot.

The interface is built around:

- an immersive Nexus experience;
- a session-aware chat console;
- a capability hub for control and configuration;
- memory, tasks, security, cognition, and system views;
- a runtime that exposes what is happening instead of hiding it behind a single text box.

That matters because people do not just want intelligence.
They want orientation.
They want to know what the system is doing, what it knows, and what it can act on next.

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

### 4. Run the backend

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

## For builders

If you are building inside this repository, the human landing page is `README.md`, while the agent-facing navigation starts with [`AGENTS.md`](AGENTS.md), then [`project.overview.md`](project.overview.md), and [`agent-start-here.md`](agent-start-here.md).

## License

BSD 3-Clause. See [`LICENSE`](LICENSE).
