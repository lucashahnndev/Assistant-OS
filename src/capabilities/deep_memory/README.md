# Deep Memory Capabilities
Use these capabilities to access your long-term, indexable storage. This memory is NOT automatically included in the prompt; you must explicit recall it.

## `deep.memory.store_memory`
Saves a piece of information permanently for future retrieval. Use this for user preferences, important facts, or complex instructions.
- **params**:
    - `content` (str): The information to save. Be descriptive.
    - `category` (str, optional): A tag for organization (e.g., 'user_preference', 'system_config', 'project_data'). Default: 'general'.

## `deep.memory.recall_memory`
Searches your deep memory for information relevant to a specific query. The results will be returned in the [OBSERVATION].
- **params**:
    - `query` (str): Keywords or a question to search for.
