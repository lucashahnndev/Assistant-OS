# Skill Contract Documentation

This document defines the interface and standards for creating and integrating new **Skills** into Assistant-OS.

## 1. Overview
Assistant-OS uses a **Modular Skill System**. Each skill is a self-contained unit capable of executing specific actions. Skills can be simple Python files or complex folders with their own configuration schemas and contracts.

## 2. Directory Structure
Skills should be placed in `src/skills/`. The recommended structure for a modular skill is:

```text
src/skills/my_new_skill/
├── __init__.py           # Entry point (required)
├── skill.py              # Main logic (recommended)
├── contract.json         # Metadata and action definitions (required)
├── config.schema.json    # (Optional) JSON Schema for skill configuration
└── README.md             # (Optional) Documentation for developers
```

## 3. The Contract (`contract.json`)
The `contract.json` file is used by the `SkillLoader` and the LLM Orchestrator to understand what your skill can do.
The `name` field defines the canonical namespace at runtime (lowercased, spaces replaced by `.`).

```json
{
  "name": "MySkill",
  "description": "Short description of what the skill does.",
  "actions": [
    {
      "id": "myskill.do_something",
      "handler": "method_name_in_class",
      "description": "Description for the LLM to know when to call this.",
      "parameters": {
        "type": "object",
        "properties": {
          "param1": { "type": "string" }
        },
        "required": ["param1"]
      }
    }
  ]
}
```

Alternative compact `actions` format is also supported:

```json
{
  "name": "my.skill",
  "actions": {
    "run": {
      "description": "Runs the main action",
      "params": {
        "query": { "type": "string" }
      }
    }
  }
}
```

In this format, action id defaults to `name + "." + key` unless `id` is explicitly set.

## 4. Implementation (`SkillBase`)
Your skill class must inherit from `SkillBase`.

### Base Class Interface
```python
from ..base import SkillBase
from typing import Dict, Any, List

class MySkill(SkillBase):
    def __init__(self, kernel, config):
        self.kernel = kernel
        self.config = config

    @property
    def name(self) -> str:
        return "myskill"

    @property
    def actions(self) -> List[str]:
        return ["do_something"]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        # Route action to specific implementation
        action = action_id.split(".")[-1]
        if action == "do_something":
            return self.handle_do_something(params)
        return {
            "ok": False,
            "status": "error",
            "error": "UNKNOWN_ACTION",
            "message": f"Unknown action: {action_id}",
            "text": f"Unknown action: {action_id}"
        }
```

## 5. Entry Point (`__init__.py`)
The loader expects a `create_skill` function in `__init__.py`.

```python
from .skill import MySkill
def create_skill(kernel, config):
    return MySkill(kernel, config)
```

## 6. System Integration Hooks

### 6.1 Configuration
Skills receive their specific configuration block from `data/config.json` via the `config` parameter in `__init__`.
To read global configs, use `self.kernel.config_manager.get("key")`.

### 6.2 Logging
Always use the centralized logging system:
```python
from utils.logging_config import get_logger
logger = get_logger("MySkill")

logger.info("Executing action...")
```

### 6.3 Workspace & Sessions
Access session-specific directories through the `kernel`:
```python
session_id = context.get("session_id")
session_dir = self.kernel.workspace_service.get_session_dir(session_id)
```

### 6.4 Playback Live (Interactive Mode)
If your skill performs visual actions (like browsing or UI interaction), you should emit playback events:

```python
from utils.event_bus import global_event_bus

# Start a run
run_id = f"run_{uuid.uuid4().hex[:8]}"
self.kernel.playback_service.start_run(session_id, run_id, "Title", source_meta)

# Emit frame
self.kernel.playback_service.add_frame(session_id, run_id, step, action, frame_bytes)
global_event_bus.emit_threadsafe({
    "type": "playback.frame",
    "run_id": run_id,
    "session_id": session_id,
    "step": step,
    "frame": { "url": f"/api/sessions/{session_id}/playback/{run_id}/frames/{filename}" }
})

# End run
self.kernel.playback_service.end_run(session_id, run_id, "success")
```

## 7. Best Practices
1. **Error Handling**: Prefer structured payloads (`ok`, `status`, `error`, `message`, `text`) over raw strings.
2. **Statelessness**: Try to keep skills stateless. Rely on the `kernel.memory_service` if persistence is needed between calls.
3. **Security**: Validate all inputs. If the skill interacts with the filesystem, use `WorkspaceService` to ensure paths remain within allowed boundaries.
4. **Resilience**: If an action is long-running, consider emitting status updates via `kernel.orchestrator.send_status`.
5. **LLM-Friendly Output**: Include a concise `text` summary plus structured fields (`results`, `best`, `count`, etc.).
6. **Contract Alignment**: Ensure `contract.json` action ids match runtime namespace and registered actions.
