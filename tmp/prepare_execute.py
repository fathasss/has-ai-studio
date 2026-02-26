import json

with open("tmp/sprint_plan_utf8.json", "r", encoding="utf-8") as f:
    plan = json.load(f)

payload = {
    "sprint_id": "SIM_SPRINT_123",
    "plan": plan
}

with open("tmp/sim_execute_payload.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
