import requests
import json
import time
import uuid

BASE_URL = "http://localhost:8000"
SPRINT_ID = f"e2e-test-{uuid.uuid4().hex[:6]}"

def test_flow():
    print(f"--- Starting E2E Test | Sprint: {SPRINT_ID} ---")
    
    # 1. Chat Preview
    print("\n[Step 1] Requesting Chat Preview...")
    preview_req = {
        "history": [
            {"role": "user", "content": "Create a simple Python 'Calculator' app with basic arithmetic operations. Use a modular structure."}
        ]
    }
    try:
        resp = requests.post(f"{BASE_URL}/chat/preview", json=preview_req, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("response", "")
        print("✓ Preview Received.")
    except Exception as e:
        print(f"✗ Preview Failed: {e}")
        return
    
    # Extract JSON Plan
    import re
    blocks = re.findall(r"```json\s*\n?(.*?)\n?```", content, re.DOTALL | re.IGNORECASE)
    plan = None
    for b in blocks:
        try:
            candidate = json.loads(b.strip())
            if isinstance(candidate, dict) and "tasks" in candidate:
                plan = candidate
                break
        except: continue
        
    if not plan:
        print("✗ FAILED: No valid JSON plan found in response.")
        print("-" * 20)
        print(content)
        print("-" * 20)
        return
    
    print("✓ Plan Parsed.")
    
    # 2. Execute Sprint
    print("\n[Step 2] Executing Sprint...")
    exec_req = {
        "sprint_id": SPRINT_ID,
        "plan": plan,
        "history": preview_req["history"]
    }
    try:
        resp = requests.post(f"{BASE_URL}/sprint/execute", json=exec_req, timeout=10)
        resp.raise_for_status()
        print("✓ Sprint Execution Started.")
    except Exception as e:
        print(f"✗ Execution Trigger Failed: {e}")
        return
    
    # 3. Monitor
    print("\n[Step 3] Monitoring progress (Wait 60s for LLM processing)...")
    for i in range(12):
        time.sleep(5)
        print(f"Waiting... { (i+1)*5 }s")
    
    print("\n[Step 4] Final Verification...")
    print(f"Check your 'apps/{SPRINT_ID}' folder for generated files.")
    print("Test Script Finished.")

if __name__ == "__main__":
    test_flow()
