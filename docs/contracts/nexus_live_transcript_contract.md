# Nexus Live Transcript Contract

This note documents the human-facing behavior of the Nexus live transcript
surface without replacing the canonical session-event spec.

## What the live card represents

- The live transcript card represents only the current turn.
- Voice and text enter the same session and share the same conversation cycle.
- The collapsible history panel remains the archival view; the live card is the
  transient view.

## Turn boundary rule

- `turn_id` is the boundary that decides when the live card resets.
- The card does not reset on every chunk.
- It resets once when a new turn begins, then keeps appending chunks for that
  same turn.
- If a payload is missing `turn_id`, the surface may fall back to transport
  context, but it must not split the live card on chunk-level changes alone.

## Voice bridge rule

- `voice.state` drives the status label for the live card.
- `asr.partial` and `transcript.partial` append to the current user text.
- `asr.final` and `transcript.final` close the current user side of the turn
  and transition the status toward thinking/responding.
- `tts.chunk` advances the assistant side of the same turn.

## User-facing result

- The live card clears at the beginning of a new user turn.
- Old transcript content stays in history, not in the live card.
- The user should see one coherent turn at a time, regardless of whether the
  input arrived by text or by voice.

## Related

- [../../agent/specs/session-event-contract.spec.md](../../agent/specs/session-event-contract.spec.md)
- [overview.md](overview.md)
