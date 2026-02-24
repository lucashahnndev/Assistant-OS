# Skill: Memory Management

Manage long-term facts and conversation context.

## Actions

### `memory.recall`
Search for historical facts or user preferences stored in deep memory.
- **Parameters**:
    - `query` (string): Keyword or phrase to search for.

### `memory.store`
Save an important piece of information for future sessions.
- **Parameters**:
    - `category` (string, optional): e.g., "preference", "user_info".
    - `content` (string): The fact to remember.

## Usage Example
```json
{
  "action": "memory.recall",
  "params": {"query": "cor favorita"},
  "response_text": "Deixe-me ver se lembro disso..."
}
```
