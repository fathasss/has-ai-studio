import requests, json

# Switch active node to local Ollama
r = requests.post('http://localhost:8000/config', json={
    "ACTIVE_NODE_ID": "default-edge"
})
print("Status:", r.status_code)
print("Response:", json.dumps(r.json(), indent=2))
