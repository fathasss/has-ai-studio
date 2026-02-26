import json
import re
import os

def try_read(path):
    for enc in ["utf-16", "utf-8", "latin-1"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except:
            continue
    return None

content = try_read("tmp/sim_preview_response.json")
if not content:
    print("ERROR: Could not read file")
    exit(1)

content = content.lstrip('\ufeff')

try:
    data = json.loads(content, strict=False)
except Exception as e:
    print(f"ERROR: JSON load failed: {e}")
    exit(1)

raw_text = data["response"]
json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL | re.IGNORECASE)

if json_match:
    plan_text = json_match.group(1)
    try:
        # Use strict=False to allow control characters like newlines within strings
        plan = json.loads(plan_text, strict=False)
        print(json.dumps(plan, indent=2))
    except Exception as e:
        print(f"ERROR: Plan JSON parse failed: {e}")
else:
    print("ERROR: JSON block not found")
