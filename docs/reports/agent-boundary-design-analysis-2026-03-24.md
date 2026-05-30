# System Audit: Agent Boundary and Semantic Authority

> Historical report. This audit describes a pre-final discovery-first boundary model and should be read as forensic context, not active contract.

Date: 2026-03-24

Scope: current repository state, verified from code and logs. This is a forensic audit of where the agent actually lives today.

## 1. Executive Diagnosis

Bluntly: the agent is distributed, not kernel-centralized.

- Semantic authority is fragmented across the orchestrator, the LLM resolver, the prompt composer, provider adapters, the intent-repair helpers, the capability registry, and the plan validator.
- Providers do influence behavior. They do not only transport tokens or parse syntax; they normalize actions, synthesize reply text, retry with repair prompts, and sometimes reconstruct intent payloads.
- The current system is not a clean kernel-authoritative model. The kernel/core is the main coordinator, but it is not the only semantic decision-maker.

The strongest evidence is structural: multiple layers independently rewrite or re-rank actions before execution, and the live logs show repeated loop-breaking and validation repair inside the kernel path itself.

## 2. Semantic Authority Map

| Decision type | File / function | Role in decision-making |
|---|---|---|
| Intent shape | [src/core/intent.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/intent.py#L5) `AgentIntent` | Canonical runtime payload for thought, plan, action, params, state summary, and response text. It defines the shape, but not the sole enforcement boundary. |
| Prompt policy | [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L128) `compose` | Injects execution policy, presentation rules, action catalog, broker guidance, assistive mode, and structured output contract into the model prompt. This is semantic policy, not formatting only. |
| Action fallback / discovery bias | [src/core/resolution/llm_resolver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/resolution/llm_resolver.py#L16) `resolve` | Forces conversational turns to `reply`, rejects empty replies, scopes allowed actions, and overrides out-of-scope actions with the discovery primary. |
| Confidence gate | [src/core/resolution/llm_resolver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/resolution/llm_resolver.py#L150) `_estimate_confidence` | Applies a semantic confidence score to the provider output and can suppress a plan entirely. |
| Scoped action set | [src/core/resolution/llm_resolver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/resolution/llm_resolver.py#L250) `_build_scoped_allowed_actions` | Narrows allowed actions to discovery candidates plus always-allowed control actions. This is semantic gating. |
| Discovery primary | [src/core/resolution/llm_resolver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/resolution/llm_resolver.py#L291) `_get_discovery_primary_action` | Picks the primary action from the current discovery state and uses it as a fallback semantic anchor. |
| Initial intent entrypoint | [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L2309) `get_initial_intent` | Builds the system prompt, calls the resolver, and applies media decision policy. This is where the kernel first turns language into a candidate action. |
| Main agent loop | [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L2435) `process` | Owns the reason-act-observe loop, plan validation, repeated-action guardrails, recovery replies, and replanning. This is the real runtime authority. |
| Action alias repair | [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L2988) action normalization block | Re-resolves action ids via the capability registry and rewrites unknown or legacy browser actions into alternate control flow. |
| Plan validation | [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L3040) `PlanValidator.validate` call site | Enforces canonical schema and policy before dispatch, and turns invalid plans into replan loops. |
| Plan safety | [src/core/plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py#L42) `validate` | Validates action existence, tool health, schema conformance, dependency availability, and destructive-action policy. |
| Plan arg mutation | [src/core/plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py#L33) `_normalize_plan_args` | Mutates `browser.control.run` args by injecting `intent_class="realizar_pesquisa"` when missing. That is semantic correction inside the kernel. |
| Capability canonicalization | [src/capabilities/registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L270) `resolve_action_id` | Canonicalizes aliases by exact, local, prefix, and fuzzy match. This is another semantic normalizer. |
| Capability dispatch | [src/capabilities/registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L231) `dispatch` | Executes the selected capability and wraps failure into structured errors. |
| Result sanitization | [src/capabilities/registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L252) `_validate_result` | Strips forbidden response fields from capability output, shaping the final response contract. |
| Provider repair helper | [src/drivers/providers/intent_repair.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/intent_repair.py#L59) `normalize_action_id` | Performs curated alias mapping, registry-based resolution, allowed-action matching, and fuzzy fallback. This is semantic repair, not transport. |
| Provider repair prompt | [src/drivers/providers/intent_repair.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/intent_repair.py#L113) `build_repair_prompt` | Injects a repair directive telling the model to fix the previous semantic violation. |
| Provider payload validation | [src/drivers/providers/intent_repair.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/intent_repair.py#L134) `validate_intent_payload` | Checks whether the model output is a valid action payload, reply, or catalog member before it is handed to the kernel. |
| Provider router | [src/services/llm/manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py#L111) `_execute_with_router` | Runs providers in priority order and falls back on provider exceptions. Provider choice therefore affects behavior. |
| Transport adapter boundary | [src/drivers/interfaces/base_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/base_driver.py#L3) `BaseDriver` | Declares protocol methods for response/status/file delivery. This is the actual driver-level boundary. |
| Internal transport bridge | [src/drivers/interfaces/internal_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/internal_driver.py#L36) `send_response` | Routes internal responses to the real interface driver; it is a protocol bridge, not the semantic governor. |

## 3. Provider Behavior Analysis

### OpenAI

Relevant code: [src/drivers/providers/openai/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/llm.py#L117), [src/drivers/providers/openai/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/llm.py#L228), [src/drivers/providers/openai/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/llm.py#L271).

- Semantic repair: yes. `_attempt_repair` rebuilds the prompt, re-queries the model, re-parses, and re-validates payloads.
- Alias normalization: yes. `normalize_action_id` is applied twice in the main path, and the allowed-action set is expanded from prompt/catalog/registry.
- Fallback logic: yes, internally via repair attempts, and externally via `LLMManager._execute_with_router`.
- Reply reconstruction: yes. `_normalize_reply_text` synthesizes a default user-facing reply when `response_text` is missing.
- Action id mutation: yes. The provider rewrites `data["action"]` after parsing and again before returning `AgentIntent`.
- Response structure mutation: yes. It normalizes attachments, plan, state_summary, task_label, and reply text.

This provider is not a pure adapter. It is an active semantic cleanup layer.

### OpenRouter

Relevant code: [src/drivers/providers/openrouter/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openrouter/llm.py#L49), [src/drivers/providers/openrouter/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openrouter/llm.py#L109), [src/drivers/providers/openrouter/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openrouter/llm.py#L236).

- Semantic repair: yes. `_attempt_repair` re-prompts the model and validates the repaired payload.
- Alias normalization: yes. `normalize_action_id` rewrites the action before the `AgentIntent` is built.
- Fallback logic: yes, both repair retry and manager-level provider fallback.
- Reply reconstruction: yes. It normalizes `response_text` from strings, dicts, lists, or missing values.
- Action id mutation: yes.
- Response structure mutation: yes, including attachments and normalized plan fields.

OpenRouter is a semantic adapter, not just a transport wrapper.

### Gemini

Relevant code: [src/drivers/providers/gemini/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/llm.py#L67), [src/drivers/providers/gemini/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/llm.py#L145), [src/drivers/providers/gemini/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/llm.py#L273), [src/drivers/providers/gemini/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/llm.py#L393).

- Semantic repair: yes, but narrower than OpenAI/OpenRouter. It validates payloads and retries with a repair prompt.
- Alias normalization: not in the main `generate_intent` path. The main intent path validates and repairs, but does not perform the same explicit `normalize_action_id` pass as OpenAI/OpenRouter.
- Fallback logic: yes, via retry attempts and contract errors.
- Reply reconstruction: yes. `_normalize_response_text` is used, and empty thought text is replaced with a default string.
- Action id mutation: only indirectly in the structured-contract path when normalizing specific structured contracts such as `browser_planner_action_v1`.
- Response structure mutation: yes, including structured vision contract normalization.

Gemini is the closest provider to a strict adapter, but it still participates in semantic validation and recovery.

### Hugging Face

Relevant code: [src/drivers/providers/huggingface/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/huggingface/llm.py#L96).

- Semantic repair: minimal.
- Alias normalization: no explicit alias canonicalization.
- Fallback logic: yes, but by collapsing non-JSON output to `AgentIntent(action="reply", response_text="")`, which intentionally pushes recovery to the orchestrator.
- Reply reconstruction: partial. It returns reply intents for non-JSON output rather than repairing the payload.
- Action id mutation: defaulting to `reply` on missing/invalid output.
- Response structure mutation: yes, but only lightly.

This is not pure transport either; it uses a semantic failure-to-reply shortcut.

### Ollama

Relevant code: [src/drivers/providers/ollama/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/ollama/llm.py#L22).

- Semantic repair: no real repair path.
- Alias normalization: no.
- Fallback logic: only coarse failure handling, returning `unknown` on JSON decode failure.
- Reply reconstruction: no substantive reconstruction.
- Action id mutation: defaulting to `unknown` on parse failure.
- Response structure mutation: minimal.

Ollama is closer to a thin parser, but it still encodes semantic defaults in failure cases.

### Shared provider helpers

Relevant code: [src/drivers/providers/intent_repair.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/intent_repair.py#L59), [src/drivers/providers/openai/parser.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/parser.py#L8), [src/drivers/providers/openrouter/parser.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openrouter/parser.py#L8), [src/drivers/providers/gemini/parser.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/parser.py#L8).

- `normalize_action_id` is a central semantic alias normalizer.
- The parser modules are not syntax-only in practice because they aggressively repair malformed JSON and scan for embedded objects.
- This means provider behavior is already mixed with semantic correction before the kernel sees the payload.

## 4. Prompt Composer Analysis

Relevant code: [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L128), [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L506), [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L528), [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L537), [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L627).

Injected policies:

- Response persona scoped to `response_text` only.
- Presentation directives that force markdown/plain/voice modes and brevity rules.
- Broker guidance that tells the model how to use evidence and live state.
- Tool discovery blocks that foreground candidate actions and primary action ids.
- Assistive mode directives that tell the model it has tool-based vision and which tools to prefer.
- Execution policy that tells the model to consult `system.control.consult_tools`, infer browser intent, and avoid retry loops.
- Structured output contract that specifies one JSON object, exact action semantics, and clarification rules.

Assessment:

- Formatter: yes, but only partially.
- Hidden policy engine: yes, decisively.

Reason:

- It does not merely serialize context.
- It embeds behavioral policy, action preferences, fallback posture, and response-shaping constraints.
- The tests explicitly confirm this behavior in [tests/minimal/test_prompt_composer_assistive_mode.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/minimal/test_prompt_composer_assistive_mode.py#L43) and [tests/minimal/test_prompt_persona_scope.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/minimal/test_prompt_persona_scope.py#L44).

## 5. Resolver and Orchestrator Analysis

Relevant code: [src/core/resolution/llm_resolver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/resolution/llm_resolver.py#L16), [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L2309), [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L2435), [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L2988), [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L3040).

`LLMResolver` is compensating for provider issues.

- It rejects empty actions.
- It rejects empty replies.
- It converts thought-only reply turns into usable reply text.
- It forces conversational turns to `reply`.
- It overrides out-of-scope actions with the discovered primary action.
- It drops low-confidence plans entirely.

The orchestrator compensates again on top of that.

- It canonicalizes action ids through the capability registry.
- It converts legacy browser actions into error/reply flows.
- It validates plans before dispatch.
- It injects validation failures back into the reasoning history to force replanning.
- It breaks repeated-action loops and synthesizes recovery replies.
- It applies media decision policy after intent resolution.

Conclusion:

- The resolver and orchestrator are not just routing layers.
- They are active semantic stabilizers.
- They are patching instability produced upstream, which is evidence of fragmented authority rather than clean kernel primacy.

## 6. Error Handling Flow

| Error class | Detected where | Handler | Retry / fallback owner |
|---|---|---|---|
| Transport errors | Provider call sites and `LLMManager._execute_with_router` | Provider exceptions bubble to the manager | [src/services/llm/manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py#L111) retries the next provider in priority order; `generate_intent` returns an `error` intent if all providers fail. |
| Syntax errors | Provider parsers and provider generate methods | Parser modules repair JSON; providers raise `ProviderContractError` when parsing or contract repair fails. | OpenAI/OpenRouter/Gemini retry repair locally before escalation; otherwise manager fallback handles it. |
| Semantic errors | Provider repair/validation, `LLMResolver.resolve`, orchestrator validation, `PlanValidator.validate` | Provider repair, resolver coercion, orchestrator rewrite, or replan loop | The kernel decides whether to replan, convert to reply, or continue. |

Observed behavior:

- OpenAI/OpenRouter/Gemini all use parser repair and/or contract errors for malformed JSON.
- `ProviderContractError` is explicitly documented as triggering kernel fallback in [src/drivers/llm/base.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/llm/base.py#L8).
- The orchestrator does not trust raw provider output; it revalidates the plan and re-enters planning on failure.

## 7. Action Validation Pipeline

Pipeline as implemented:

1. Provider output is parsed or repaired into a dict.
2. Provider adapter normalizes `action`, `response_text`, attachments, and related fields.
3. Provider returns `AgentIntent`.
4. `LLMResolver.resolve` validates action presence, reply completeness, conversational fit, scope, and confidence.
5. Orchestrator resolves aliases again with `capability_registry.resolve_action_id`.
6. Orchestrator calls `PlanValidator.validate`.
7. Capability registry dispatch executes the capability.
8. Registry result validation strips forbidden response fields.

Where invalid actions slip through:

- Before kernel validation, because providers already canonicalize and repair them.
- Between resolver and orchestrator, because the resolver accepts a plan that is later invalidated by the plan validator.
- Into recovery loops, because the orchestrator can convert unknown actions into a reply and keep processing.

Where correction happens:

- Provider adapters correct malformed or ambiguous output.
- The resolver corrects semantic scope.
- The orchestrator corrects aliases and unknown actions.
- The plan validator corrects browser-control args by injecting defaults.

This is not a single validation gate. It is a distributed correction pipeline.

## 8. Provider Dependency Analysis

Evidence from code:

- `LLMManager._execute_with_router` executes providers in priority order and falls back on exceptions.
- OpenAI and OpenRouter normalize actions and reconstruct reply text.
- Gemini validates and repairs without the same explicit alias-canonicalization path in the main intent flow.
- Hugging Face and Ollama fail differently on malformed output, which produces different downstream agent states.

Concrete implication:

- The same user input can produce different downstream behavior depending on provider and provider order because the adapters do not share identical semantic repair paths.
- This is an inference from code paths, not a paired live A/B trace.

Observed runtime instability:

- [data/logs/llm.log](/home/lucas/Documentos/GitHub/Assistant-OS/data/logs/llm.log#L82) shows repeated `browser.control.close` loops until the orchestrator breaks the loop.
- [data/logs/llm.log](/home/lucas/Documentos/GitHub/Assistant-OS/data/logs/llm.log#L103) and [data/logs/llm.log](/home/lucas/Documentos/GitHub/Assistant-OS/data/logs/llm.log#L139) show repeated `browser.control.close_instance` validation failures because `instance_id` is missing.
- [data/logs/llm.log](/home/lucas/Documentos/GitHub/Assistant-OS/data/logs/llm.log#L17) shows the orchestrator rejecting hallucinated state summary content and rolling back state.

These logs prove instability in the action-selection and validation path, even without provider names attached to the trace.

## 9. Contract Enforcement

Is there a single canonical schema?

- No.

Where schema enforcement exists:

- `AgentIntent` in [src/core/intent.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/intent.py#L5).
- Prompt contract in [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L627).
- OpenAI JSON schema in [src/drivers/providers/openai/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/llm.py#L179).
- Gemini JSON mode and strict structured parser in [src/drivers/providers/gemini/llm.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/llm.py#L67).
- Capability parameter schemas in [src/capabilities/registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L298) and [src/core/plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py#L80).

Who enforces it:

- Providers enforce syntax and payload shape.
- The resolver enforces semantic acceptability.
- The orchestrator enforces action legality and loop control.
- The plan validator enforces canonical capability schema and policy.

Determinism:

- Partially deterministic at each layer.
- Not deterministic end-to-end, because multiple layers can rewrite the same payload in different ways.

## 10. Root Causes

These are the real architectural drift causes:

- Policy leakage into the prompt composer.
- Semantic repair inside provider adapters.
- Multiple action canonicalizers spread across layers.
- Provider pool fallback in the manager.
- Validator mutation of plan arguments before validation.
- Orchestrator rewrites of unknown actions into alternate control flow.
- Absence of one authoritative action gateway between model output and dispatch.

## 11. Risk Assessment

- Unpredictability: the same semantic mistake can be “fixed” differently by different providers.
- Provider-dependent behavior: the manager and adapters make provider selection behaviorally visible.
- Debugging difficulty: the system can correct the same error in multiple places, obscuring the true source of failure.
- Scaling risk: multi-agent and worker flows will inherit the same ambiguity unless the kernel becomes the single semantic authority.
- Loop risk: the live log shows repeated wrong-action loops and repeated validation failures that require kernel-side bailout.

## 12. Anti-Patterns Identified

- Provider as semantic fixer.
- Prompt as policy engine.
- Distributed decision making.
- Hidden fallback in adapters.
- Hidden fallback in the provider manager.
- Validator that mutates plans before enforcing them.
- Multiple alias normalizers with overlapping authority.
- Recovery loops compensating for upstream semantic drift.

## Final Verdict

The current system is not kernel-authoritative in the strict architectural sense you want.

- The kernel is the main coordinator, but it is not the only semantic authority.
- Providers actively reshape intent.
- The prompt composer injects policy.
- The resolver and orchestrator patch instability.
- The registry and validator also participate in semantic correction.

That is why behavior can diverge by provider and why the system still shows loop and validation pathology in live logs.

## Architecture Correction Plan

### 1. Target Architecture

Final boundary:

- Kernel/Core = single semantic authority.
- Provider = pure transport + syntax layer.
- Driver = protocol adapter only.

Target data flow:

1. User input enters the kernel through the driver.
2. Kernel builds context and selects a provider.
3. Provider returns raw structured output or a transport/syntax error.
4. Kernel parses and classifies the result.
5. Kernel routes the candidate through the Action Gateway.
6. Action Gateway validates, canonicalizes, and resolves the action deterministically.
7. Kernel executes or rejects the plan.
8. Kernel decides retry, fallback, replan, or abort.

Boundary rules:

- Providers do not decide meaning.
- Providers do not rewrite actions.
- Providers do not pick fallback actions.
- Providers do not synthesize semantic reply text.
- Providers do not expand allowed actions.
- Providers do not interpret capabilities.

### 2. New Components

#### ActionGateway

Location:

- `src/core/action_gateway.py`

Responsibilities:

- validate `action_id`
- canonicalize `action_id`
- check `allowed_actions`
- validate params against capability schema
- classify action-level failures
- return a deterministic resolution outcome

Interface:

```python
class ActionGateway:
    def resolve(self, plan, allowed_actions, capability_registry, context) -> ActionResolutionResult:
        ...
```

Output:

- resolved action id
- validated params
- validation status
- deterministic failure reason

#### ErrorClassifier

Location:

- `src/core/error_classifier.py`

Responsibilities:

- classify raw provider failures into `TransportError`, `SyntaxError`, or `AgentSemanticError`
- attach machine-readable codes
- preserve original provider error metadata

Interface:

```python
class ErrorClassifier:
    def classify(self, error, raw_output=None) -> ClassifiedError:
        ...
```

#### ContractValidator

Location:

- `src/core/contract_validator.py`

Responsibilities:

- validate provider result shape only
- validate JSON structure only
- validate required fields only
- reject semantic repair

Rule:

- this validator returns pass/fail and a syntax/contract reason
- it does not mutate payloads

#### ProviderResult

Location:

- `src/core/provider_result.py`

Responsibilities:

- carry raw provider payload
- carry parsed syntax result
- carry provider metadata
- carry transport status

Suggested shape:

```python
class ProviderResult(BaseModel):
    ok: bool
    raw_text: str = ""
    parsed: dict | None = None
    provider_name: str
    model: str
    error_type: str | None = None
    error_code: str | None = None
```

### 3. Provider Contract

Providers must accept:

- `system_prompt`
- `history`
- `user_input`
- optional multimodal payloads
- max token and timeout limits

Providers must return:

- raw text
- parsed JSON object if syntax extraction succeeds
- transport metadata
- error classification if a failure occurs

Providers must be forbidden from:

- rewriting `action_id`
- canonicalizing aliases
- expanding `allowed_actions`
- inferring fallback actions
- reconstructing `response_text`
- repairing semantic gaps
- choosing retries across providers

Provider rule:

- providers only emit structure or failure
- all meaning stays in the kernel

### 4. Action Pipeline

Final sequence:

1. Kernel constructs context.
2. Kernel sends request to provider.
3. Provider returns raw output or error.
4. ContractValidator checks syntax and required fields.
5. Kernel parses the payload into a provider result.
6. ErrorClassifier maps failures into one of the strict error classes.
7. Kernel sends the candidate action to ActionGateway.
8. ActionGateway validates and canonicalizes.
9. Kernel executes the resolved capability.
10. Kernel handles post-execution success or failure.

Where each step lives:

- Steps 1, 5, 6, 7, 8, 9, 10 live in the kernel.
- Step 2 lives in the provider.
- Step 3 is returned by the provider.
- Step 4 is a pure contract layer in the kernel boundary.

### 5. Error Flow Design

#### TransportError

Examples:

- network failure
- timeout
- auth failure
- rate limit
- billing failure
- provider unavailable

Handling:

- detected at provider call time
- classified immediately by `ErrorClassifier`
- kernel retries the next provider if retry budget remains
- kernel aborts if all providers fail

#### SyntaxError

Examples:

- invalid JSON
- malformed output
- truncation
- parse failure

Handling:

- detected by `ContractValidator`
- classified as syntax failure
- kernel retries the same provider once if policy allows
- kernel then switches provider or aborts based on retry budget

#### AgentSemanticError

Examples:

- invalid `action_id`
- action outside allowed set
- missing required params
- capability mismatch

Handling:

- detected by `ActionGateway`
- classified as semantic failure
- kernel owns the next decision
- kernel replans, asks for clarification, chooses a different action, or aborts

Decision rules:

- transport failure -> provider switch
- syntax failure -> retry bounded by policy
- semantic failure -> kernel replan or fallback
- repeated semantic failure -> abort or ask for clarification

### 6. Migration Plan

#### Phase 1: Isolation

Goal:

- stop providers from performing semantic repair

Actions:

- remove `normalize_action_id` usage from provider main paths
- remove provider-side fallback action synthesis
- remove provider-side reply reconstruction
- remove provider repair loops
- keep syntax parsing only
- preserve old behavior behind feature flags for one release

Safety:

- add logging when providers would have rewritten data
- keep old code paths reachable only under a temporary compatibility flag

#### Phase 2: Centralization

Goal:

- move all action resolution into `ActionGateway`

Actions:

- add `ActionGateway.resolve`
- route all post-LLM action handling through it
- remove alias normalization from resolver and providers
- remove capability-based action rewriting from orchestrator
- make gateway the only canonicalization point

Safety:

- shadow-run the gateway in parallel before enforcing it
- compare gateway output with current output
- log divergence before switching to enforcement mode

#### Phase 3: Cleanup

Goal:

- remove duplicate normalization layers

Actions:

- simplify `LLMResolver` to semantic scoring and request routing only
- simplify `PromptComposer` to context formatting only
- remove validation mutation from `PlanValidator`
- remove parser-layer semantic repair
- remove provider retry prompts that alter meaning

Safety:

- keep compatibility adapters that translate old result formats into new kernel-bound models
- preserve old schema names while deprecating old behavior

#### Phase 4: Hardening

Goal:

- enforce the new architecture permanently

Actions:

- make provider contract violations fail fast
- make semantic violations kernel-owned only
- make ActionGateway the only action canonicalization path
- make PlanValidator pure
- add deterministic contract tests for every provider
- add regression tests for action id stability, fallback stability, and replay consistency

Safety:

- promote contract failures to explicit errors
- remove feature flags only after parity is verified

### 7. Backward Compatibility Strategy

Maintain stability during migration by using parallel enforcement.

Strategy:

- keep existing provider adapters active while shadow-running the new kernel path
- log old-vs-new action resolution for every turn
- compare resolved action ids before execution
- compare provider parse outputs before dispatch
- gate enforcement behind staged feature flags

Regression detection:

- action id drift
- provider-specific reply drift
- action selection drift
- fallback drift
- schema mismatch drift

Compatibility rules:

- do not change public driver interfaces first
- do not remove old provider fields until kernel consumers are migrated
- do not enforce strict failure mode until the gateway is in place

### 8. Risk Analysis

Breakpoints:

- providers that currently rely on repair prompts
- flows that depend on implicit alias normalization
- browser and calendar actions with legacy parameter gaps
- hidden fallback paths in long-running loops

Instability points:

- first enforcement of strict provider output
- first removal of provider-side semantic repair
- first activation of centralized action resolution
- first removal of validator mutation

Mitigation:

- phase every change behind feature flags
- shadow-run the new path before enforcement
- log divergences with enough detail to replay the turn
- keep the kernel able to fall back to a safe `reply` or clarification path

### 9. Success Criteria

The migration is complete only when all of the following are true:

- provider output no longer affects semantic behavior
- only the kernel resolves action meaning
- only one Action Gateway canonicalizes actions
- no provider rewrites `action_id`
- no provider synthesizes fallback actions
- no validator mutates plan data
- provider failures are classified strictly as transport or syntax failures
- semantic failures are handled only by kernel policy
- action validation is deterministic across providers
- replaying the same input produces the same kernel decision regardless of provider

### 10. Implementation Order

Recommended sequence:

1. Add `ProviderResult`, `ErrorClassifier`, and `ContractValidator`.
2. Add `ActionGateway` and route action resolution through it.
3. Strip semantic repair from providers.
4. Remove alias normalization from provider and resolver paths.
5. Make `PromptComposer` context-only.
6. Make `PlanValidator` pure.
7. Remove duplicate repair loops and hidden fallback logic.
8. Turn on strict enforcement and delete compatibility shims.

### 11. Final Design Rule

After migration, the only place allowed to decide what an action means is the kernel.

Providers return structure.
Drivers move bytes.
Everything else must stop pretending to be semantic authority.

## 13. Critical Review and Failure Analysis

### Plan Consistency Check

- The plan is not fully consistent because `ActionGateway` is assigned validation, canonicalization, classification, and fallback decision-making at once. That is orchestrator behavior with a narrower name.
- The plan says `ContractValidator` validates syntax and required fields only, but required-field checks already depend on schema semantics. The boundary is not clean unless the validator is limited to structural shape and raw JSON well-formedness.
- The plan says the kernel owns retry, fallback, replan, and abort decisions, but the `ActionGateway` section also says it returns a deterministic resolution outcome and classifies failures. That splits the policy boundary.
- The plan says providers only parse syntax, but the provider contract still asks them to return parsed JSON objects and structured errors. That is acceptable only if parsing is strictly syntax-level and never retries or repairs semantics.

### Boundary Violation Risks

- Providers can leak semantics back in through parser heuristics, because the current parser helpers in [src/drivers/providers/openai/parser.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/parser.py#L8), [src/drivers/providers/openrouter/parser.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openrouter/parser.py#L8), and [src/drivers/providers/gemini/parser.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/parser.py#L8) already do more than JSON tokenization.
- PromptComposer can leak semantics back in if it keeps any of the current policy payloads from [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L528) or [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L627).
- Validators can leak semantics back in the moment they start adding defaults, coercing params, or turning invalid data into a recoverable shape. The current mutation example in [src/core/plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py#L33) proves how easily that boundary erodes.
- The gateway can leak semantics back in if it owns both action resolution and fallback policy. That turns it into the new orchestrator.

### ActionGateway Analysis

- The gateway is overloaded in the proposal.
- It currently tries to own canonicalization, allowed-set checking, parameter validation, failure classification, and deterministic outcome selection.
- That is too broad for a single boundary object if the kernel must remain the sole semantic authority.
- Split the gateway into a narrow resolution facade and separate kernel-owned policy modules.

Required split:

- `ActionResolver` for canonicalization only.
- `ActionValidator` for schema and capability checks only.
- `FallbackPolicy` inside the kernel for retry, fallback, clarification, and abort.

If the gateway keeps fallback decision-making, the system will recreate the same central ambiguity that currently exists in [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L3040) and [src/services/llm/manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py#L111).

### ContractValidator Analysis

- The syntax and semantics boundary is not clean in the current proposal.
- A validator that checks “required fields” is already reading semantic expectations from a schema.
- A validator that checks “provider result shape only” must limit itself to JSON object validity, field presence, and type shape.
- Anything beyond that, including “missing required params” in a domain-specific schema, belongs to the kernel action layer.
- If the validator starts deciding whether a missing field is tolerable or can be defaulted, semantic leakage returns immediately.

Failure points:

- multiple JSON blocks in one response
- valid JSON with the wrong action
- structurally valid payload with missing capability params
- payload that is syntactically valid but contextually impossible

### Provider Layer Risks

- Providers can still leak semantics indirectly if they keep repair prompts or if parsers keep heuristic extraction that selects the “best” object instead of failing fast.
- Retry mechanisms can hide contract drift by turning one bad model reply into several silent correction attempts.
- Response normalization can become semantic if it rewrites missing reply text, default action ids, or param structures.
- The proposed restriction is only valid if provider code is reduced to transport, raw parsing, and explicit error emission.

### Error Handling Edge Cases

#### Valid JSON, wrong action

- Expected behavior: kernel classifies it as `AgentSemanticError`.
- Gap: if the gateway canonicalizes aliases too aggressively, a wrong action can be treated as a near-match instead of a failure.

#### Partial valid structure

- Expected behavior: `ContractValidator` rejects the payload as syntax/contract failure.
- Gap: if the parser tries to salvage partial semantics, it recreates provider-side repair.

#### Repeated invalid action

- Expected behavior: kernel records the semantic failure signature, increments a bounded counter, and aborts or replans after the policy threshold.
- Gap: without a kernel-owned failure ledger, repeated invalid actions will loop through provider, parser, and gateway repeatedly.

#### Missing required parameters

- Expected behavior: `ActionGateway` rejects the action and returns a semantic error to the kernel.
- Gap: if any layer supplies defaults, the system silently mutates intent.

#### Multiple JSON blocks

- Expected behavior: parser fails unless the contract explicitly allows one unambiguous object and one only.
- Gap: heuristic “first object wins” parsing reintroduces silent semantic selection.

### Retry Strategy Validation

- Retry is not yet sufficiently bounded in the proposal.
- The provider retry path and the kernel retry path overlap unless one owner is assigned.
- The plan must define exactly one retry counter per turn and one retry counter per provider.
- Retries can mask deeper problems if they are triggered by semantic failures instead of transport failures.
- Retry policy must be consistent across providers or provider choice will continue to change behavior.

### Migration Plan Risks

- The highest regression risk is Phase 1, because removing provider repair exposes every hidden dependency on the current messy behavior.
- The second highest risk is Phase 2, because centralizing action resolution will reveal how many call sites already assume local normalization.
- The fragile points are the current provider adapters, `LLMResolver`, and the existing plan validation path in the orchestrator.
- Hidden dependencies include tests and runtime flows that currently depend on silent reply synthesis, alias repair, or fallback-to-next-provider behavior.

### Determinism Check

- The system will not produce the same result across providers as currently specified.
- The reason is simple: different models emit different raw outputs, and the plan still allows provider-level syntax handling and provider selection order.
- Divergence remains possible in parser heuristics, output formatting, tokenization differences, and provider availability.
- Determinism is achievable only after freezing provider behavior to a narrow syntax contract and pushing all semantic decisions into one kernel policy path.

### Missing Components

- Missing kernel-owned fallback policy module.
- Missing kernel-owned retry ledger.
- Missing canonical action schema registry that is separate from capability execution.
- Missing replay harness for provider parity checks.
- Missing observability for semantic-failure signatures and resolution divergence.
- Missing explicit contract for multiple JSON blocks versus single-object outputs.
- Missing explicit “same-turn semantic hash” to detect repeated failures without relying on action text alone.

### Failure Modes

- First break: provider output no longer gets silently repaired, so malformed replies will surface immediately.
- Second break: ActionGateway will reject many actions that currently pass via alias repair.
- Third break: long-running loops that depended on hidden fallback logic will stop progressing.
- Recovery path: the kernel must decide whether to replan, clarify, or abort based on a bounded semantic-failure ledger.

### Hardening Recommendations

- Split `ActionGateway` into resolution, validation, and policy modules.
- Keep fallback, retry, and clarification decisions in a separate kernel policy component.
- Keep `ContractValidator` syntax-only and fail-fast.
- Delete parser heuristics that choose among multiple embedded JSON objects.
- Delete provider-side repair loops completely.
- Add one kernel-owned semantic failure ledger per turn.
- Add shadow-mode parity checks before each enforcement step.
- Add explicit observability for provider drift, gateway divergence, and repeated semantic failures.

## 14. Strict Refinement Blueprint

### 14.1 Critical Ambiguities

Definitions:

- Contract: the runtime envelope that moves from provider boundary to kernel boundary. It includes raw text, parsed payload, provider metadata, and error classification.
- Schema: the structural definition of fields and types for a single payload shape.
- Capability validation: the kernel check that a canonical action id is registered, allowed, and parameter-valid against capability metadata.

Boundary rules:

- Structural validation ends at JSON well-formedness, top-level object shape, and field type checks.
- Semantic validation begins the moment action meaning, capability choice, allowed set membership, or parameter adequacy is evaluated.
- Syntax repair means extraction, fence stripping, and safe delimiter closure only.
- Semantic repair means any action rewrite, param fill, alias normalization, fallback selection, or reply synthesis.

Required fields by stage:

- Provider stage: `raw_text`, `provider_name`, `model`, transport status, and parse status.
- Contract stage: parsed JSON object or explicit syntax failure.
- Action stage: canonical `action_id`, `params`, `allowed_actions`, and capability metadata.
- Execution stage: resolved action id, validated params, and execution context.

### 14.2 ContractValidator

Purpose:

- validate provider output structure only

Input:

- `raw_text`
- optional `parsed` JSON object
- `provider_name`
- `model`
- `strict_mode` flag

Output:

- `ok: bool`
- `error_type: SyntaxError | None`
- `error_code`
- `parsed`

Validations:

- JSON object validity
- single top-level object only
- top-level field presence required by the transport contract
- field type checks for structure only
- brace, bracket, and quote balancing for truncated payload recovery

Forbidden behavior:

- inferring missing fields
- filling parameters
- canonicalizing `action_id`
- expanding allowed actions
- choosing a fallback action
- rewriting `response_text`
- coercing a malformed semantic payload into a valid semantic payload

Exact failure conditions:

- multiple top-level JSON objects
- malformed JSON after safe extraction
- non-object top-level payload when object is required
- truncated payload that cannot be closed safely
- missing required transport fields

### 14.3 ActionGateway Decomposition

#### ActionCanonicalizer

Responsibility:

- map exact aliases to canonical action ids

Inputs:

- raw `action_id`
- explicit alias map
- capability registry exact lookup

Outputs:

- canonical `action_id`
- alias resolution status

Forbidden behavior:

- fuzzy matching
- heuristic guessing
- semantic fallback
- capability ranking

Alias rule:

- explicit mapping only
- fuzzy matching: `NO`

#### ActionValidator

Responsibility:

- validate canonical action against allowed actions, capability registration, and parameter schema

Inputs:

- canonical `action_id`
- `params`
- `allowed_actions`
- capability metadata

Outputs:

- validation pass/fail
- semantic error code
- validation diagnostics

Forbidden behavior:

- selecting an alternative action
- injecting default params
- repairing missing params
- retrying providers
- choosing fallback policy

#### ActionDecision

Responsibility:

- encode kernel decision for the validated action result

Inputs:

- validation result
- kernel policy result

Outputs:

- `EXECUTE`
- `REPLAN`
- `CLARIFY`
- `ABORT`

Forbidden behavior:

- action inference
- action ranking
- provider selection
- payload mutation

### 14.4 Provider Parser Hard Limits

Allowed:

- extract one JSON object from text
- remove markdown fences
- close truncated braces, brackets, or quotes without adding content

Forbidden:

- inferring missing keys
- correcting `action_id`
- filling `params`
- restructuring payload meaning
- merging multiple JSON objects
- selecting the “best” object from noisy output

Examples:

- Allowed: `{"action":"reply"}` extracted from fenced markdown.
- Allowed: `{"a":1` repaired to `{"a":1}` only by delimiter closure.
- Forbidden: turning `{"action":"weathe","params":{}}` into `weather.control.get`.
- Forbidden: turning an object with no `response_text` into a synthesized reply.

### 14.5 Retry Strategy

Global rule:

- max provider invocations per turn: `2`
- same-provider retry count: `0`
- same-turn provider switch count: `1`

Rules:

- TransportError triggers one provider switch and no same-provider retry.
- SyntaxError triggers one provider switch and no same-provider retry.
- AgentSemanticError triggers no provider retry.
- The kernel stops after the second provider failure and returns a deterministic failure path.

Loop prevention:

- one provider failure ledger per turn
- one action failure ledger per turn
- one provider switch per turn

### 14.6 PromptComposer

Boundary:

- context formatter only

Allowed:

- session metadata
- user language
- current state snapshot
- capability inventory string
- raw tool summary
- driver capability string

Forbidden:

- action suggestions
- fallback instructions
- capability prioritization
- execution hints
- policy injection
- retry advice

### 14.7 PlanValidator

Boundary:

- validation only
- no mutation

Allowed:

- check action exists
- check params against schema
- check runtime capability health
- return `PlanValidationError`

Forbidden:

- default param injection
- plan rewriting
- alias correction
- fallback choice
- clarification generation

Failure behavior:

- validator returns error
- kernel decides replan, clarify, or abort

### 14.8 Error Handling Map

TransportError:

- owned by provider manager
- provider switch only
- no semantic repair

SyntaxError:

- owned by the kernel contract boundary
- provider switch only
- no semantic repair

AgentSemanticError:

- owned by the kernel action path
- replan, clarify, or abort only
- no provider retry

Ownership:

- retry: provider manager for transport and syntax only
- replan: kernel only
- fallback: kernel only

### 14.9 STRICT_MODE

Activation:

- `STRICT_MODE=true` in kernel configuration
- kernel passes the flag into provider config and action pipeline

Behavior:

- providers perform syntax extraction only
- providers do not repair semantics
- ActionCanonicalizer uses explicit mapping only
- ActionValidator rejects rather than repairs
- ActionDecision returns kernel-owned outcomes only

Migration use:

- shadow mode first
- log strict vs legacy divergence
- enforce strict mode per provider after parity passes

Enforcement:

- assertion on provider semantic-repair imports
- assertion on provider alias normalization usage
- assertion on validator mutation attempts
- assertion on fuzzy matching code paths

### 14.10 Final Refined Architecture

Flow:

1. User -> Driver
2. Driver -> Kernel
3. Kernel -> Provider
4. Provider -> Kernel
5. Kernel ContractValidator
6. Kernel ActionCanonicalizer
7. Kernel ActionValidator
8. Kernel ActionDecision
9. Kernel execution

Components:

- Kernel: planning, policy, retries, fallback, replan, clarification, abort
- Provider: transport and syntax extraction only
- Driver: protocol and interface only
- ActionGateway: canonicalization and validation facade only
- Kernel policy module: fallback and retry decisions only

### 14.11 Implementation Guardrails

- Ban provider imports from `intent_repair.normalize_action_id`
- Ban provider-side repair prompt generation
- Ban validator mutation methods
- Ban fuzzy matching in action canonicalization
- Ban prompt composer policy strings in provider code
- Ban multiple provider retries per turn
- Ban action selection outside kernel action path
- Add tests that fail on semantic mutation outside kernel
- Add tests that fail on provider action rewriting
- Add tests that fail on validator mutation
- Add tests that compare strict-mode and legacy-mode divergence
