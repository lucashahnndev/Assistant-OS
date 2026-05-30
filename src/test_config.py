import json
with open('/home/lucas/Documentos/GitHub/Assistant-OS/data/config.json', 'r') as f:
    config = json.load(f)
edge = next(p for p in config['cortex']['audio']['tts'] if p['provider'] == 'edge_tts')
print("VOICE IN JSON:", edge.get('voice'))
