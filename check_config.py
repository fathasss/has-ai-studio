import requests, json
r = requests.get('http://localhost:8000/config')
c = r.json()
print('Active Node ID:', c.get('ACTIVE_NODE_ID'))
for n in c.get('NODES', []):
    marker = ' <<<' if n['id'] == c.get('ACTIVE_NODE_ID') else ''
    print(f"  {n['id']}: {n['name']} ({n['provider']}) -> {n.get('url','N/A')}{marker}")
