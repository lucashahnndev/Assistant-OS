from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

with open(ROOT / 'frontend/src/pages/Chat.jsx', 'r') as f:
    content = f.read()

paren_stack = []
for i, char in enumerate(content):
    if char == '(':
        paren_stack.append(i)
    elif char == ')':
        if not paren_stack:
            print(f"Extra closed parenthesis at index {i}")
            start = max(0, i - 40)
            end = min(len(content), i + 40)
            print(f"Snippet: {content[start:end]}")
        else:
            paren_stack.pop()

if paren_stack:
    for start_index in paren_stack:
        print(f"Unclosed open parenthesis at index {start_index}")
        start = max(0, start_index - 40)
        end = min(len(content), start_index + 40)
        print(f"Snippet: {content[start:end]}")
