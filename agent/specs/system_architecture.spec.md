# Atlas Bot (Assistant-OS) System Architecture

## Overview
Atlas Bot is a modular, agentic AI assistant designed for Linux systems. It employs a **Kernel-Driver-Service** architecture to decouple low-level I/O from high-level reasoning. The core intelligence is driven by an LLM-based Orchestrator that operates in a ReAct (Reason-Act) loop.
The agent operating model itself is defined in [atlas_operating_model.spec.md](atlas_operating_model.spec.md) and should be used as the behavioral contract for how the orchestrator reasons, acts, and recovers inside the runtime.

---

## 1. Core Architecture

### 1.1 Kernel (`src/main.py`)
The **Kernel** is the central nervous system.
- **Responsibilities**:
    - Initializes the application.
    - Loads and manages **Drivers**.
    - Routes messages between Drivers and the **AgentOrchestrator**.
    - Manages the main event loop.
- **Data Flow**: `Driver -> Kernel -> Orchestrator -> Kernel -> Driver`

### 1.2 Drivers (`src/drivers/`)
Drivers are the interface between the internal logic and the external world. All drivers must inherit from `BaseDriver`.
- **BaseDriver Contract**:
    - `start()`: Start blocking/async loops.
    - `stop()`: Clean shutdown.
    - `send_response(text)`: Output text to the user.
    - `send_file(target, path, caption)`: Send attachments (new).
- **Implementations**:
    - **TelegramDriver**: Bi-directional chat via Telegram Bot API. Async-based.
    - **VoiceDriver**: PyGame UI + STT/TTS. Handles local voice interaction.
    - **BrowserDriver**: Controls a web browser via Playwright. Used for automation (YouTube, Web Search).
    - **ServerDriver**: RestAPI/WebSocket interface (currently a stub for future IPC).

### 1.3 AgentOrchestrator (`src/core/orchestrator.py`)
The **Brain**. It implements a cognitive architecture.
- **Process**:
    1.  **Input**: Receives text + metadata (Channel, User) from Kernel.
    2.  **Context**: Loads `Session` (Short-term memory) and `MemoryService` (Long-term memory).
    3.  **Reflex**: Handles only explicit commands, internal events, emergency conditions, and technical fallback paths.
        Semantic interpretation remains with the LLM and context layer; regex-based fast paths must not act as the semantic authority.
    4.  **Reasoning Loop**:
        - Queries LLM with System Prompt + History.
        - Parses JSON response into `AgentIntent`.
        - Executes Actions (`send_file`, `search_web`, `play_music`, etc.).
        - Updates Working Memory/Scratchpad.
        - Repeats until `action='reply'` or step limit reached.

---

## 2. Memory Architecture

### 2.1 Session Memory (`src/services/session_manager.py`)
Ephemeral, conversational context.
- **Structure**:
    - `history`: List of messages (User/Assistant/System).
    - `working_memory`: "RAM" for the agent. Editable via `working_memory_op`.
    - `scratchpad`: Internal monologue/reasoning trace.
    - `plan`: List of tasks for complex goals.
    - `context`: Metadata (User ID, Channel Name, OS Info).

### 2.2 Long-Term Memory (`src/services/memory/`)
Persistent storage using vector embeddings (ChromaDB) and JSON.
- **Deep Memory**: Semantic search for past conversations.
- **Fact Store**: Key-Value pairs for explicit user preferences (e.g., "User likes Python").
- **Summaries**: Compressed logs of past sessions.

---

## 3. Skill System

Skills are discrete capabilities the Agent can invoke.
- **Discovery**: The System Prompt lists available skills.
- **Execution**: `_execute_action` method in Orchestrator maps Intent Actions to methods.
- **Current Skills**:
    - `search_web`: Google Search (via Browser or Default).
    - `play_music`: YouTube playback (BrowserDriver).
    - `send_file`: Upload local files to user.
    - `system_apps`: Launch local Linux applications.
    - `recall_memory` / `store_memory`: Interaction with LTM.

---

## 4. Configuration
- **ConfigManager (`src/config/manager.py`)**: Loads `data/config.json`.
- **Environment**: `.env` file for secrets (API Keys, Tokens).

## 5. Directory Structure
```
src/
├── core/           # Orchestrator, Intent, System Prompts
├── drivers/        # I/O Adapters (Telegram, Voice, Browser)
├── models/         # Data structures (Session, Assistant)
├── services/       # Business Logic (LLM, Memory, TTS)
├── skills/         # Documentation for LLM
├── utils/          # Helpers (Logging, Text Process)
└── main.py         # Entry Point
```
