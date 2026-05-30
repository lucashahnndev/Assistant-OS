import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def check_syntax(filename):
    with open(filename, 'r') as f:
        content = f.read()

    # Mask strings and comments to avoid confusion
    # Mask strings
    content = re.sub(r'\'(\\\'|[^\'])*\'', lambda m: 'S' * len(m.group(0)), content)
    content = re.sub(r'\"(\\\"|[^\"])*\"', lambda m: 'S' * len(m.group(0)), content)
    content = re.sub(r'`(\\`|[^`])*`', lambda m: 'S' * len(m.group(0)), content)
    # Mask comments
    content = re.sub(r'//.*', lambda m: 'C' * len(m.group(0)), content)
    content = re.sub(r'/\*.*?\*/', lambda m: 'C' * len(m.group(0)), content, flags=re.DOTALL)
    # Mask regex
    content = re.sub(r'\/(\\\/|[^\/])+\/[gimuy]*', lambda m: 'R' * len(m.group(0)), content)

    paren_stack = []
    brace_stack = []
    
    for i, char in enumerate(content):
        if char == '(':
            paren_stack.append(i)
        elif char == ')':
            if not paren_stack:
                print(f"Extra closed parenthesis at index {i} (line {content.count('\n', 0, i) + 1})")
                print(f"Snippet: {content[i-20:i+20]!r}")
            else:
                paren_stack.pop()
        elif char == '{':
            brace_stack.append(i)
        elif char == '}':
            if not brace_stack:
                print(f"Extra closed brace at index {i} (line {content.count('\n', 0, i) + 1})")
                print(f"Snippet: {content[i-20:i+20]!r}")
            else:
                brace_stack.pop()

    if paren_stack:
        for p in paren_stack:
            print(f"Unclosed open parenthesis at index {p} (line {content.count('\n', 0, p) + 1})")
            print(f"Snippet: {content[p-20:p+20]!r}")
            
    if brace_stack:
        for b in brace_stack:
            print(f"Unclosed open brace at index {b} (line {content.count('\n', 0, b) + 1})")
            print(f"Snippet: {content[b-20:b+20]!r}")

check_syntax(str(ROOT / 'frontend/src/pages/Chat.jsx'))
