# Calendar Discoverability

This capability is the user's internal calendar and agenda surface.

- Use `calendar` when the user asks about their own agenda, schedule, events, appointments, or local calendar entries.
- This is the canonical path for `data/calendar/events.json` and other internal calendar state.
- Use it before any external retrieval path when the question is about the user's own calendar.
- The `discoverability_profile` exists so `system.control.consult_tools` can surface it semantically.
- Keep calendar-specific discovery terms here, not in the kernel.
- Good discovery terms: internal calendar, local calendar, my calendar, minha agenda, meu calendário, eventos locais, compromissos.
