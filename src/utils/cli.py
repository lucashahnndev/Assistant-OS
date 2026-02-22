import os

def clear_console():
    """Clears the terminal console in a cross-platform way."""
    os.system('cls' if os.name == 'nt' else 'clear')
