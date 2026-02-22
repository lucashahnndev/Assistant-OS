# Skill: System Control

Monitor and manage high-level system states and information.

## Actions

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
