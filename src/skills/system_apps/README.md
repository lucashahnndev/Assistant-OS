# Skill: System Applications

Manage local applications and system window states.

## Actions

### `open_program`
Launch a local application or a web app shortcut (e.g., "youtube music", "chrome").
- **Parameters**: 
    - `program_name` (string): Name of the application. Alias: `app`, `target`, `app_name`.
- **Logic**: Attempts to use `xdg-open` or direct execution on Linux.

### `key_command` (Integrated via specific actions)
Direct window controls via automated key presses.
- **Maximizar**: Use `maximize_window` (if implemented) or key commands.
- **Fechar**: Use `close_window` (if implemented).

### `find_program`
Checks if a program is installed by searching for the best match.
- **Parameters**:
    - `program_name` (string): The name to search for.

### `close_program` (key_command based)
Attempts to close the current active window.
- **Parameters**: None.

## Usage Example
```json
{
  "action": "find_program",
  "params": {"program_name": "chrome"},
  "response_text": "Verificando se o Chrome está instalado..."
}
```
