# Capability: System Logs

Retrieve internal system logs to diagnose errors or monitor process flow.

## Actions

### `read_logs`
Reads the most recent entries from the `assistant.log` file.
- **Parameters**: None.
- **Logic**: Returns the last 20 lines of the system log.

## Usage Example
```json
{
  "action": "read_logs",
  "params": {},
  "response_text": "Deixe-me verificar o que aconteceu nos bastidores..."
}
```

## When to use
- If a command seems to have failed without a clear error message.
- To check the result of a background process.
- To understand why the agent behaved in a certain way.
