# Calendar Adaptive Alert Architecture Spec

## 1) Objective
Build a reliable and adaptive event alert system that combines:
- deterministic scheduling and safety controls
- agentic personalization and policy evolution

This avoids hardcoded-only behavior while preventing uncontrolled autonomous side effects.

---

## 2) High-Level Topology
`CalendarEvent -> AlertPolicyEngine -> NotificationOrchestrator -> DeliveryRouter -> FeedbackCollector -> EventObserver -> PolicyStore`

---

## 3) Core Components

### 3.1 `AlertPolicyEngine` (Deterministic Core)
Responsibilities:
- generate `alert_plan` per event using current policies and context
- ensure safe fallback when context is incomplete
- produce stable and traceable decisions

Input:
- event metadata, such as start, duration, type, source and title
- user policy profile
- runtime context, such as timezone, active channel and quiet hours

Output (`alert_plan`):
- offsets in minutes before or at start
- priority per offset
- channel strategy
- dedupe keys per alert

Fallback:
- baseline offsets, for example `30/10/1`, when no adaptive profile exists

### 3.2 `NotificationOrchestrator`
Responsibilities:
- receive `alert_plan` and execute scheduled notifications
- enforce dedupe, rate limits and quiet-hour policy
- produce notification intent with structured context, not hardcoded final text

### 3.3 `DeliveryRouter`
Responsibilities:
- resolve best delivery targets, such as active session versus push
- avoid duplicate sends across overlapping targets and channels
- retry, backoff and fallback by interface health

### 3.4 `FeedbackCollector`
Responsibilities:
- collect outcomes: delivered, read, responded, ignored, snoozed and delayed
- transform raw outcomes into compact utility signals

### 3.5 `EventObserver` (Agentic Layer)
Responsibilities:
- analyze historical utility signals
- propose policy updates, such as offset changes, channel preference and priority or tone strategy
- never bypass the deterministic delivery pipeline

Constraint:
- observer proposes policy patches; application may require approval based on risk level

### 3.6 `PolicyStore`
Stores:
- `global_policy`
- `user_policy`
- `event_class_policy` when needed

Requirements:
- versioned
- auditable, with who, why and when
- precedence rules explicit, such as `event > user > global > fallback`

---

## 4) Data Contracts

### 4.1 `alert_plan`
```json
{
  "event_id": "uuid",
  "alerts": [
    {
      "offset_min": 30,
      "priority": "medium",
      "channel_strategy": "active_session_preferred",
      "dedupe_key": "calendar:event_starting:<event_id>:30"
    }
  ],
  "policy_version": "user:v12"
}
```

### 4.2 `notification_intent` (structured)
```json
{
  "source_domain": "calendar",
  "priority": "high",
  "as_agent_message": true,
  "message_context": {
    "event_type": "calendar.event_starting",
    "event_id": "uuid",
    "title": "Event title",
    "start_time": "ISO-8601",
    "offset_min": 0,
    "instruction": "Notify user in persona style, concise and actionable."
  },
  "metadata": {
    "dedupe_key": "calendar:event_starting:<event_id>:0"
  }
}
```

### 4.3 `policy_patch` (observer output)
```json
{
  "scope": "user",
  "target": "user_123",
  "changes": {
    "default_offsets": [20, 5, 0],
    "preferred_channel": "telegram"
  },
  "reason": "low engagement at 30min, higher response at 5min",
  "confidence": 0.82,
  "risk_level": "low",
  "requires_approval": false
}
```

---

## 5) End-to-End Flow
1. Event is created or updated.
2. `AlertPolicyEngine` computes `alert_plan`.
3. Scheduler stores upcoming alert triggers.
4. On trigger time, `NotificationOrchestrator` emits structured `notification_intent`.
5. Agent, through the persona layer, renders final user-facing wording from context.
6. `DeliveryRouter` sends with dedupe and rate-limit safeguards.
7. `FeedbackCollector` records delivery and user response outcomes.
8. `EventObserver` periodically proposes policy improvements.
9. `PolicyStore` applies approved changes and increments policy version.

---

## 6) Guardrails
- hard dedupe key: `event_id + offset + time_bucket`
- max alerts per event, day and user
- strict quiet-hours policy with emergency override
- observer cannot send notifications directly
- medium or high-risk policy changes require explicit approval
- every policy mutation is audit logged

---

## 7) Why This Is Agentic-Safe
- keeps deterministic reliability in the critical path
- uses agentic reasoning for adaptation, not raw execution
- preserves observability, rollback and predictable behavior

---

## 8) Incremental Rollout Plan

### Phase A (MVP)
- deterministic `AlertPolicyEngine`
- policy store, global plus user
- structured intents plus persona rendering
- dedupe and rate limits

### Phase B
- feedback collection and engagement metrics
- observer suggestions in read-only or recommendation mode

### Phase C
- low-risk auto-apply policy patches
- approval workflow for higher-risk changes
- A/B policy evaluation by user segment

---

## 9) Initial Defaults Recommendation
- keep `30/10/1` as fallback only
- start adaptive profile after minimum evidence threshold
  - for example, at least 20 delivered alerts and 7-day history

---

## 10) Success Metrics
- duplicate notification rate
- on-time reminder delivery rate
- user engagement rate, such as reply, open or snooze
- false-positive annoyance rate
- policy change rollback rate
