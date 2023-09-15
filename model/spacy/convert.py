import yaml
import json
import collections.abc

with open('data.yml', 'r') as f:
    data = yaml.safe_load(f)

with open('data.json', 'w') as f:
    json.dump(data, f)
