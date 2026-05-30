# 1. Executive Summary

> Historical report. Skill terminology and catalog assumptions here may predate the current discovery-first contract.
The current skills system is a mixed abstraction: it behaves at the same time as tool runtime, integration package format, prompt catalog source, and partial policy metadata source.

In runtime terms, a skill is a Python class (`SkillBase`) loaded from `src/skills/<folder>` by convention, then registered as namespaced actions in `SkillRegistry`.

The architecture is functional but overloaded. The same “skill” unit currently carries:
- executable action handlers,
- contract metadata (for UI/discovery/policy hints),
- optional reflex rules,
- configuration schema,
- sometimes heavy runtime assets (for example browser profiles/cache under `src/skills/browser_control/profiles`).

Core strengths today:
- Simple loading model (`create_skill` factory + folder convention).
- Unified dispatch path through registry.
- Principal-aware prompt filtering (`get_allowed_actions`) and pre-dispatch gate support.
- On-demand action catalog mode to reduce prompt footprint.

Main weaknesses today:
- Contract/schema inconsistency (`params` vs `parameters`, list vs dict action formats).
- Skill metadata is used by multiple components with divergent assumptions.
- Validation is partial and sometimes mismatched to real contract shape.
- “Skill” includes concerns that are not strictly tool execution.
- Some execution paths bypass normal registry dispatch (example weather card route).

# 2. Current Definition of "Skill"
In code, the canonical base is `SkillBase` (`src/skills/base.py:5`). A skill must provide:
- `name` (`src/skills/base.py:8`),
- `actions` list (`src/skills/base.py:13`),
- `execute(action_id, params, context)` (`src/skills/base.py:18`).

Optional behaviors:
- Reflex rules (`get_reflex_rules`, `src/skills/base.py:36`).
- LLM documentation hook (`get_documentation`, `src/skills/base.py:40`) exists but is not used in current runtime.

In practice, a skill is not only an executable tool. It is a mixed container of:
- action handlers,
- contract metadata (`contract.json`),
- config schema (`config.schema.json`),
- UI and discovery metadata,
- occasionally domain assets and implementation-specific runtime files.

So conceptually today it is a mixed abstraction (tool + integration package + behavior metadata), not a clean plugin-only primitive.

# 3. Skill Package/Internal Structure
Observed package patterns in `src/skills/*`:
- mandatory runtime files: `__init__.py` with `create_skill`, class module (`skill.py` or `*_skill.py`),
- contract metadata: `contract.json`,
- optional config schema: `config.schema.json`,
- optional docs/manifest: `README.md`, `manifest.json`,
- optional support modules/assets: `backends/`, `extension/`, `profiles/`.

Concrete examples:
- Factory pattern: `src/skills/web_search/__init__.py:1-2`, `src/skills/browser_control/__init__.py:1-4`.
- Contract + schema usage: loader reads `contract.json` and `config.schema.json` (`src/skills/loader.py:71-113`).
- Mixed metadata formats in contracts:
  - dict-style `actions` + `params` (example `maps_search`, `web_search`),
  - list-style `actions` + `parameters` (example `system_control`, `task_management`).

Special case artifacts:
- `src/skills/index/manifest.json` and `src/skills/index/README.md` are documentation index artifacts, but this folder has no `__init__.py`, so it is not loaded as runtime skill.

# 4. Skill Registration and Loading
## Discovery and loading
`SkillLoader.load_from_directory` scans folders in `src/skills` (`src/skills/loader.py:52-65`):
- ignores folders starting with `__` and `shared` (`src/skills/loader.py:63`),
- requires `__init__.py` (`src/skills/loader.py:70-76`),
- imports module dynamically and requires `create_skill` (`src/skills/loader.py:84-85`).

## Config binding
Per-skill config is read from global config key by folder name (`skills.<folder>`) (`src/skills/loader.py:87-92`).

Enablement gate is checked before instantiation (`src/skills/loader.py:93-96`).

## Contract attachment and namespacing
If `contract.json` exists, loader stores it on instance as `_contract` and computes `_namespace` from contract `name` lowercased and dotified (`src/skills/loader.py:121-127`).

This creates dual identity:
- config identity: folder name,
- runtime namespace identity: contract name-derived namespace.

## Registry registration
`SkillRegistry.register` maps each action to full ID, prefixing namespace when action is local (`src/skills/registry.py:62-77`).

Dispatch path: `SkillRegistry.dispatch` resolves action -> `skill.execute` -> result contract sanitization (`src/skills/registry.py:82-129`).

# 5. Skill Exposure to the Agent
Skill exposure is done through action catalogs, not by injecting full skill code/contracts.

Main surfaces:
- `SkillRegistry.get_summary/get_compact_manifest/get_focus_actions/get_catalog` (`src/skills/registry.py:265-363`).
- Prompt injection through orchestrator (`src/core/orchestrator.py:5004-5051`, `5130-5214`).
- Discovery actions served by `system_control` skill (`system.control.skills.*`) (`src/skills/system_control/skill.py:190-335`, contract entries in `src/skills/system_control/contract.json:46+`).

Important runtime behavior:
- Agent prompt exposure is principal-filtered via `allowed_actions` when context exists (`src/core/orchestrator.py:5004-5007`).
- For on-demand mode, prompt may include only discovery actions instead of full action list (`src/core/orchestrator.py:5147-5183`).

# 6. Skill Interaction with Prompt Construction
Prompt construction path:
- Orchestrator computes action block via `_build_prompt_actions_block` (`src/core/orchestrator.py:5130-5214`).
- Composer injects `[AVAILABLE ACTIONS]` with clipping budget (`src/services/llm/prompt_composer.py:266-270`).

Modes affecting token load (`src/core/orchestrator.py:5135+`):
- `full`: injects full textual summary (`SkillRegistry.get_summary`).
- `on_demand`: injects discovery bootstrap actions and rules, deferring catalog expansion to runtime actions.
- `compact_*`: injects compact JSON manifest + focus shortlist.

Token controls:
- `skills_summary` block budget default 2200 chars (`src/services/llm/prompt_composer.py:81-90`).
- Global budgets scaled down when provider context is small (`src/core/orchestrator.py:5008-5019`).

Observations:
- Prompt strategy is already aware of token pressure.
- In `compact_hybrid` modes, `a` still contains full action IDs array (`src/core/orchestrator.py:5211`), which can grow significantly as action count increases.

# 7. Skill Interaction with Sessions and Memory
## Session interaction model
During dispatch, skills receive restricted session view `_SkillSessionView` (`src/core/orchestrator.py:52-70`, `2721-2733`):
- allows reading `session_id` and `context`,
- blocks direct `add_message` and `publish_event` calls.

However, `context` dict is passed through directly (`src/core/orchestrator.py:63`), so skills can mutate `session.context` keys indirectly.

## Persistence and restoration
Session persistence is generic and not skill-specific (`src/core/session.py:137-225`, `src/core/orchestrator.py:1100-1160`).

No dedicated skill state restoration layer exists; state persistence is embedded in generic session fields, work context, scheduler files, and per-skill internal files.

## Memory interaction
Skills access memory service through kernel/orchestrator references:
- `memory_management` and `deep_memory` call `orch.memory_service` (`src/skills/memory_management/skill.py:34-72`, `src/skills/deep_memory/skill.py:37-71`).

Agent-level retrieval memory is composed separately by orchestrator/prompt flow, not as a skill-managed lifecycle.

# 8. Skill Interaction with Chroma / Retrieval
Chroma services:
- Long-term memory: `MemoryService` -> `data/memory/chroma` (`src/services/memory/memory_service.py:15-27`).
- Episodic memory: `EpisodicMemoryService` -> `data/memory/chroma_episodic` (`src/services/memory/episodic_memory.py:16-27`).

Skill-facing usage:
- Memory skills call memory service query/add methods directly.
- Web retrieval/search skills do not use Chroma directly; they use deterministic retrieval helpers (`src/skills/shared/retrieval.py`) and provider routers (`web_search`).

Cross-skill retrieval orchestration:
- `research_retrieve` dispatches to other skills through a constrained wrapper allowlist (`src/skills/research_retrieve/skill.py:15-52`).
- This indicates “skill composition” inside skill runtime, not a separate orchestration layer.

# 9. Skill Execution Model
Execution flow today:
1. LLM resolver returns `ActionPlan` (`src/core/resolution/llm_resolver.py:58-72`).
2. Plan is validated (`PlanValidator.validate`) (`src/core/plan_validator.py:31+`).
3. Orchestrator builds `exec_context` and dispatches to registry (`src/core/orchestrator.py:2721-2750`).
4. Registry invokes `skill.execute` and sanitizes forbidden conversational fields (`src/skills/registry.py:94-129`).

Selection logic:
- Active chain is `FallbackChainResolver([LLMResolver])` (`src/core/orchestrator.py:149-156`).
- Reflex resolver is initialized but not in active resolver chain.

Parameter validation:
- `PlanValidator` tries to read action schema from contract `actions` and field `params` (`src/core/plan_validator.py:69-85`).
- Many contracts use `parameters` (JSON Schema style), so validation coverage is inconsistent.

Failure handling:
- Unknown action and execution exceptions return structured errors from registry (`src/skills/registry.py:96-110`).
- Orchestrator logs dispatch failures and maps some failures to error codes (`src/core/orchestrator.py:2764+`).

# 10. Token Cost and Prompt Inflation Analysis
Major skill-related token drivers today:
- `[AVAILABLE ACTIONS]` block itself (`skills_summary`).
- Full action list in compact payload (`"a"`) for non-on-demand modes.
- Skill descriptions when `full`/descriptive modes are used.

Mitigations already present:
- Block clipping budget (`PromptComposer._BLOCK_BUDGETS['skills_summary']=2200`) (`src/services/llm/prompt_composer.py:81-90`).
- On-demand catalog mode with bootstrap discovery actions (`src/core/orchestrator.py:5147-5183`).
- Principal filtering reduces visible action universe (`src/core/access_controller.py:719-760`).

Remaining inflation risks:
- Large action fleets still inflate compact manifest payload (`a` list).
- Descriptions from contracts can be verbose and inconsistent.
- Prompt block competition: skills_summary competes with memory, attachments, state blocks under constrained context windows.

# 11. Architectural Problems in the Current Skill Model
## 11.1 Overloaded abstraction
“Skill” simultaneously represents:
- executable action runtime,
- metadata/contract unit,
- UI catalog source,
- policy hint source (`risk_level`),
- optional behavior/reflex pack.

This is a catch-all abstraction with weak boundary separation.

## 11.2 Contract format fragmentation
Contracts vary by:
- `actions` as dict or list,
- params schema under `params` or `parameters`,
- uneven metadata completeness.

Runtime consumers implement different parsing assumptions (`SkillRegistry`, `PlanValidator`, API routes), increasing drift risk.

## 11.3 Partial safety dependence on context path
Pre-dispatch access gate is applied when principal context is available in orchestrator dispatch path (`src/core/orchestrator.py:2737-2750`).

Any bypass/nonstandard execution path can reduce enforcement consistency.

## 11.4 Registry-dispatch bypass exists
Example: weather card route instantiates `WeatherSkill` directly and calls `execute` without registry dispatch (`src/server/routes/sessions.py:707-726`).

This bypasses registry-level cross-cutting behaviors (result sanitization, discoverability semantics).

## 11.5 Result contract friction
`SkillBase`/registry discourage conversational fields, but several skills still return `message`. Registry strips forbidden fields (`src/skills/registry.py:117-127`), which can silently drop information if skills rely on those keys.

## 11.6 Skill package boundary leakage
Runtime mutable artifacts under `src/skills` (e.g. browser profiles) mix deployable code and operational state, complicating packaging and lifecycle hygiene.

## 11.7 Inactive/partial subsystems
Reflex infrastructure is built and rules are collected (`src/core/orchestrator.py:138-147`), but resolver chain currently uses only `LLMResolver` (`src/core/orchestrator.py:155`).

# 12. Recommended Conceptual Separation
For conceptual clarity (without implementation details yet), separate concerns into four explicit layers:
- Action Runtime Layer: executable handlers and dispatch contracts only.
- Capability Metadata Layer: declarative action/permission/risk catalog normalized to one schema.
- Prompt Exposure Layer: token-aware capability summarization/discovery strategy independent from handler packaging.
- Integration Package Layer: optional connectors/assets/config/docs, isolated from runtime mutable state.

In this model, “skill” should stop being the sole container for policy, UI, and execution concerns. It should become either:
- a pure runtime capability module, or
- a package that clearly declares subcomponents per concern.

# 13. Suggested Future Direction
Near-term direction for refactor readiness:
- Establish one canonical action contract schema and adapter for legacy contracts.
- Enforce single dispatch authority (registry path) for all skill action execution surfaces.
- Keep least-privilege exposure as first-class (principal-filtered catalogs + pre-dispatch gate).
- Treat prompt catalog generation as its own subsystem with measurable token budgets and diagnostics.
- Isolate runtime mutable artifacts out of skill source tree.
- Decide explicit role of reflex rules (active resolver stage vs deprecated optional metadata).

This keeps current runtime model reusable while reducing ambiguity in what a “skill” is and how it participates in planning, policy, and execution.
