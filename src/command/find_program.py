import difflib
import subprocess

import winapps

def get_installed_programs():
    programs = []
    apps = winapps.list_installed()
    for app in apps:
        programs.append(app.name)
    return programs


def find_program(name):
    # obter a lista de programas instalados
    installed_programs = get_installed_programs()

    print(installed_programs)
    # encontrar o programa mais semelhante
    best_match = difflib.get_close_matches(name.lower(), installed_programs, n=1, cutoff=0.5)
    
    if best_match:
        print(best_match)
        print(best_match[0])
        return best_match[0]
    else:
        return None

