import json
import sys
import os
#obter o cominho do arquivo
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#ir para parent_dir
sys.path.append(parent_dir)


file_config = open(f'{parent_dir}\\data\\config.json', 'r')
config = json.load(file_config)

#ffmpeg
FFMPEG_PATH = f"{parent_dir}/tools/ffmpeg/bin"
os.environ["PATH"] += os.pathsep + FFMPEG_PATH

#bot
BOT_NAME = config['chatterbot']['nameBot']

#openai
OPENAI_API_KEY = config['openai']['token']
OPENAI_ORGANIZATION_ID = config['openai']['organization_id']

#google
GOOGLE_CLOUD_API_KEY = config['google_cloud']['token']
GOOGLE_MAPS_API_KEY = config['google_maps']['token']