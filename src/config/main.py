import json
import sys
import os
#obter o cominho do arquivo
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#ir para parent_dir
sys.path.append(parent_dir)


config_path = os.path.join(parent_dir, 'data', 'config.json')
file_config = open(config_path, 'r')
config = json.load(file_config)

# FFMPEG is expected to be in the system PATH. 
# On Windows, you can add its bin folder to PATH manually or logic can be added here.
if os.name == 'nt':
    # Legacy support for local tools folder if present
    potential_ffmpeg = os.path.join(parent_dir, 'tools', 'ffmpeg', 'bin')
    if os.path.exists(potential_ffmpeg):
        os.environ["PATH"] += os.pathsep + potential_ffmpeg

#bot
BOT_NAME = config['agent']['agent_name']