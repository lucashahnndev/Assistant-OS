# Capability: System Control

Monitor and manage high-level system states and information.

## Actions

### `consult_tools`
Performs semantic discovery of candidate tools/capabilities from the current user input or an explicit query.
- **Parameters**: `query` (optional; falls back to the current user input when omitted), `intent`, `domain`, `role`, `entity_type`, `limit`, `include_descriptions`, `format`.
- **Behavior**: Returns a ranked candidate set plus a primary action suggestion for the next planner step.

### `system_status`
Returns CPU usage, RAM/swap, disk usage, uptime, top 5 processes, and temperature (if available).
- **Parameters**: None.

### `hardware_info`
Returns CPU model, total RAM, disk information, GPU details, and network interfaces.
- **Parameters**: None.

### `os_info_extended`
Returns detailed distribution info, kernel version, hostname, current user, desktop environment, and timezone.
- **Parameters**: None.

### `save_snapshot_state`
Generates a comprehensive system snapshot bundle (status + hardware + OS + processes + basic network) saved to the project's work artifacts directory.
- **Parameters**: None.

## Usage Example

```json
{
  "thought": "O usuário quer saber como está o desempenho do PC.",
  "action": "system_status",
  "params": {},
  "response_text": "Deixa eu dar uma olhada no fôlego do sistema..."
}
```
