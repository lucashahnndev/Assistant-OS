# 1. Executive Summary
The codebase has three real plugin-like domains, but naming is mixed:

- **Interfaces (channel adapters)**: concrete runtime adapters for Web/API+WS, Telegram, Voice, and a special `system` host adapter.
- **Model Drivers / Intelligence Providers**: LLM providers and TTS providers loaded via generic `PluginLoader` pools with fallback routing.
- **Capability Plugins (currently called "skills")**: operational packages loaded from `src/skills/*` and dispatched by namespaced action IDs.

The architecture works, but the term **"skill" is conceptually overloaded**. It currently covers operational tooling, orchestration helpers, discovery/catalog utilities, and some policy/meta behavior.

There is also an important boundary blur: `SystemDriver` lives under `drivers/interfaces` but functions as a host-capability backend consumed by skills, not as a user communication channel.

# 2. Current Conceptual Domains Found in the Codebase
## Domain A: Interfaces (human/admin channels)
- Kernel loads channel drivers from `interfaces` config (`src/main.py:103-123`).
- Common protocol is `BaseDriver` (`src/drivers/interfaces/base_driver.py:3-94`).
- Active concrete drivers in code: `server`, `telegram`, `voice` (+ `system` loaded as driver).

## Domain B: Model Drivers / Intelligence Providers
- LLM pool: `LLMManager` + providers in `src/drivers/providers/*` loaded with `PluginLoader` (`src/services/llm/manager.py:44-109`).
- TTS pool: `TTSManager` + providers in `src/services/tts/providers/*` loaded with `PluginLoader` (`src/services/tts/manager.py:28-67`).
- STT is partially present as config + voice assistant runtime path, but no source manager/provider files in `src/services/stt` (only `__pycache__` present).

## Domain C: Capability Plugins / Operational Packages
- Runtime abstraction: `SkillBase` (`src/skills/base.py:5-42`).
- Loader: `SkillLoader` scanning `src/skills` folders (`src/skills/loader.py:52-130`).
- Registry/dispatch: `SkillRegistry` (`src/skills/registry.py:28-110`).
- Orchestrator execution bridge: `AgentOrchestrator` (`src/core/orchestrator.py:130-136`, `2721-2750`).

# 3. Interfaces
## What it is
Channel adapters that receive user/admin input and return responses/events.

## Responsibility
- Session/channel ingress and egress.
- Transport-specific formatting and capabilities.
- Building `PrincipalContext` for access control and least privilege.

## Implementations
- **Web/Portal/WS**: `ServerDriver` (`src/drivers/interfaces/server_driver.py:48+`) and FastAPI app factory (`src/server/main.py:45-77`).
- **Telegram**: `TelegramDriver` (`src/drivers/interfaces/telegram/telegram_driver.py:15+`).
- **Voice (local interface)**: `VoiceDriver` (`src/drivers/interfaces/voice/voice_driver.py:13+`).
- **Voice over web protocol**: `VoiceManager` used by `ServerDriver` (`src/drivers/interfaces/server_driver.py:73-76`, `src/server/voice_manager.py:45+`).

## How loaded
- Kernel reads `interfaces` config and instantiates enabled drivers (`src/main.py:103-123`).

## Interaction with rest of system
- Drivers call `kernel.process_input(...)` via `BaseDriver.on_message_received` (`src/drivers/interfaces/base_driver.py:77-83`).
- Drivers pass principal metadata (`PrincipalContext`) (e.g. `server_driver.py:253-258`, `voice_driver.py:174-181`).
- Driver capabilities influence prompt/presentation mode via session context (orchestrator reads these flags, `src/core/orchestrator.py:4955-5002`).

## Separation quality
- Web/Telegram/Voice are clearly interface adapters.
- **Mixing issue**: `SystemDriver` is in `drivers/interfaces` but is not a user channel; it is host-control backend APIs (status/process/fs/network/etc.) (`src/drivers/interfaces/system_driver.py:58+`).

# 4. Model Drivers / Intelligence Providers
## What it is
Provider adapters for intelligence services (LLM and TTS), with pool-based fallback routing.

## Responsibility
- Connect to external/local model backends.
- Normalize provider outputs to internal contracts.
- Provide fallback when a provider fails.

## Implementations
### LLM
- Manager/router: `src/services/llm/manager.py`.
- Provider interface with contract normalization: `src/drivers/llm/base.py` (`ILLMProvider`, browser/vision structured normalization).
- Provider modules: `src/drivers/providers/gemini/llm.py`, `.../openai/llm.py`, `.../openrouter/llm.py`, `.../ollama/llm.py`, `.../huggingface/llm.py`.

### TTS
- Manager/router: `src/services/tts/manager.py`.
- Provider interface: `src/services/tts/providers/base.py`.
- Providers: `google.py`, `edge.py`, `system.py`.

### STT
- Config exists (`ConfigManager.get_stt_config`, `src/config/manager.py:239-255`).
- Runtime uses voice assistant initialization path in `VoiceDriver`/`VoiceManager` (`voice_driver.py:50-97`, `voice_manager.py:107-117`).
- **But** source STT provider/manager modules are absent in `src/services/stt` (only pycache files), indicating incomplete or legacy-migrated subsystem.

## How loaded
- LLM/TTS use generic `PluginLoader.load_plugins(...)` (`src/utils/plugin_loader.py:9-59`).
- LLM: scans `src/drivers/providers/*` directories (`src/services/llm/manager.py:48-60`).
- TTS: scans `src/services/tts/providers` (`src/services/tts/manager.py:30-33`).

## Interaction with rest of system
- Orchestrator instantiates `LLMManager` and uses it for planning, summarization, and structured vision calls.
- Voice flows use `TTSManager` and assistant STT path.

## Separation quality
- LLM and TTS are reasonably modular.
- **Mixing issues**:
  - Duplicate/parallel LLM interface definitions (`src/drivers/llm/base.py` and `src/drivers/providers/base.py`).
  - STT architecture appears half-migrated.

# 5. Capability Plugins / Operational Packages
## What it is
Operational modules currently called **skills**, each exposing actions for orchestrator execution.

## Responsibility
Provide concrete agent capabilities: browser automation, search/retrieval, filesystem/shell/system operations, app control, memory operations, vision, task orchestration.

## Implementations and examples
- Browser automation package: `src/skills/browser_control/*` (`browser_control_skill.py`).
- Web retrieval/search packages: `web_search`, `web_retrieve`, `wikipedia_search`, `youtube_*`, `maps_search`, `research_retrieve`.
- Host ops packages: `system_control`, `shell_control`, `system_apps`, `system_logs`.
- Perception package: `vision`.
- Memory wrappers: `memory_management`, `deep_memory`.
- Task/scheduler wrapper: `task_management`.

## How loaded
- Folder convention (`src/skills/<skill>/__init__.py` with `create_skill`) via `SkillLoader` (`src/skills/loader.py:66-130`).
- Enabled/disabled by config under `skills.<folder>.enabled` (`src/skills/loader.py:87-96`).
- Actions registered/namespaced in `SkillRegistry` (`src/skills/registry.py:62-77`).

## Interaction with rest of system
- Orchestrator dispatches plans through registry (`src/core/orchestrator.py:2721-2750`).
- Access control applies action allow/deny/risk filtering (`src/core/access_controller.py:670-760`).
- Prompt exposure is built from registry catalogs (`src/core/orchestrator.py:5130-5214`).

## Separation quality
- Good reuse of a single action runtime path.
- Mixed concerns inside this domain:
  - pure operational capabilities,
  - catalog/discovery actions (`system.control.skills.*`),
  - orchestration/meta actions (`task.*`, `reflex.skill.*`),
  - docs/index artifacts in `src/skills/index` not runtime-loaded.

# 6. Where the Current "Skill" Term is Overloaded
## What codebase currently calls a "skill"
A class implementing `SkillBase` loaded from `src/skills` with actions dispatched by registry.

## Which current skills are actually capability plugins
Mostly these are true capability plugins:
- `browser_control`, `web_search`, `web_retrieve`, `maps_search`, `wikipedia_search`, `youtube_search`, `youtube_retrieve`, `research_retrieve`,
- `shell_control`, `system_control`, `system_apps`, `system_logs`,
- `vision`, `weather_control`,
- `memory_management`, `deep_memory` (memory capability wrappers).

## Skills that are less "capability" and more meta/orchestration/policy
- `task_management` (scheduler/work management façade),
- `reflex_skill` (meta-control + reflex bridging),
- parts of `system_control` (`system.control.skills.list*`, `describe*`) act as catalog/discovery service rather than operational capability.

## Are components treated as skills that should be interfaces/model drivers?
- No strong case of a channel interface being implemented as a skill in current code.
- No LLM/TTS provider is implemented as a skill; they are separate plugin systems.
- But there is the inverse confusion: `SystemDriver` is under interfaces yet semantically a capability backend.

## Is naming overloaded?
Yes. "Skill" currently mixes:
- tool runtime,
- capability package,
- metadata/catalog carrier,
- policy hint source,
- some orchestration/meta logic.

# 7. Recommended Conceptual Taxonomy
A cleaner conceptual taxonomy for this project:

1. **Interface Adapters**
- Web/WS, Telegram, Voice, future WhatsApp/CLI.
- Own ingress/egress, user identity, and channel capabilities.

2. **Intelligence Providers**
- LLM chat/vision providers.
- STT providers.
- TTS providers.
- Uniform provider contracts + pool routing/fallback.

3. **Capability Plugins**
- Operational action packages executed by orchestrator.
- Strictly actions and execution contracts.

4. **Platform Backends**
- Host/system adapters such as `SystemDriver` and browser runtime/session registries.
- Not user interfaces; infrastructure for capability plugins.

5. **Control Plane / Catalog Services**
- Action discovery, metadata exposure, ACL/risk layers.
- Keep separate from operational capabilities even if currently implemented in `system_control` actions.

# 8. Key Refactor Implications
1. **Rename domains in code and docs**
- Keep backward compatibility for "skills" externally, but internally classify as `capability_plugins`.

2. **Relocate or reclassify `SystemDriver`**
- Move from interface namespace to platform/backend namespace, or explicitly tag as non-channel driver.

3. **Normalize plugin contracts**
- Keep LLM/TTS providers under unified provider contract framework.
- Remove duplicate `ILLMProvider` definition drift (`drivers/llm/base.py` vs `drivers/providers/base.py`).

4. **Stabilize STT architecture**
- Either restore source-based STT provider manager module or retire legacy references.

5. **Split capability vs control-plane actions**
- Catalog/introspection actions (`system.control.skills.*`) should be in control-plane module, not mixed with host operations.

6. **Keep orchestrator reuse but tighten boundaries**
- Current runtime loop can stay; taxonomy and package boundaries should become explicit to reduce conceptual debt.
